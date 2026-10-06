// kv-chat-notify — membangunkan agent lewat "webhook routine" saat staf mengirim pesan chat.
// Dipanggil oleh trigger DB (pg_net) dengan body {"message_id": "<uuid>"}; verify_jwt dimatikan karena
// trigger tidak membawa JWT. Keamanan: fungsi ini tidak mempercayai body — ia mengklaim pesan lewat RPC
// kv_chat_notify_claim (service_role saja), yang hanya mengembalikan wake=true SEKALI untuk pesan staf
// berstatus pending yang belum pernah dinotifikasi. Panggilan palsu/ulang tidak berbuat apa-apa.
//
// Secret Edge Function (Dashboard > Edge Functions > Secrets), <AGENT> = id agent huruf besar, mis. CONTENT:
//   WEBHOOK_URL_<AGENT>          URL webhook routine agent (wajib agar agent dibangunkan)
//   WEBHOOK_KEY_<AGENT>          kunci pengirim (opsional)
//   WEBHOOK_AUTH_HEADER[_<AGENT>] nama header kunci (bawaan "Authorization")
//   WEBHOOK_AUTH_PREFIX[_<AGENT>] awalan nilai header (bawaan "Bearer " untuk Authorization, "" untuk header lain)
// Bila URL belum diset, pesan tetap "pending" (wake_status = belum_dikonfigurasi) dan staf melihat "menunggu".
// Isi chat TIDAK pernah dikirim ke webhook; agent mengambilnya sendiri lewat agent-chat.py.

const SB_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const REPO = "/workspace/vertex8-virtual-office-repo";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
function env(name: string): string | undefined {
  const v = Deno.env.get(name);
  return v === undefined ? undefined : v.trim();
}
async function rpc(name: string, args: Record<string, unknown>): Promise<unknown> {
  const r = await fetch(`${SB_URL}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!r.ok) throw new Error(`rpc ${name} HTTP ${r.status}`);
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ ok: false, error: "metode harus POST" }, 405);
  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { return json({ ok: false, error: "body bukan JSON" }, 400); }
  const id = String(body?.message_id ?? "");
  if (!UUID_RE.test(id)) return json({ ok: false, error: "message_id tidak valid" }, 400);
  if (!SB_URL || !SERVICE_KEY) return json({ ok: false, error: "env Supabase tidak tersedia" }, 500);

  let claim: Record<string, unknown>;
  try {
    claim = (await rpc("kv_chat_notify_claim", { p_message_id: id })) as Record<string, unknown>;
  } catch (e) {
    console.error("klaim gagal:", (e as Error).message);
    return json({ ok: false, error: "klaim gagal" }, 500);
  }
  if (!claim?.wake) return json({ ok: true, woke: false, reason: claim?.reason ?? "tidak_perlu" });

  const agent = String(claim.agent ?? "");
  const agentName = String(claim.agent_name ?? agent);
  const suf = agent.toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const url = env(`WEBHOOK_URL_${suf}`);
  const key = env(`WEBHOOK_KEY_${suf}`);
  let status = "belum_dikonfigurasi";

  if (url) {
    const header = env(`WEBHOOK_AUTH_HEADER_${suf}`) || env("WEBHOOK_AUTH_HEADER") || "Authorization";
    const prefix = env(`WEBHOOK_AUTH_PREFIX_${suf}`) ?? env("WEBHOOK_AUTH_PREFIX") ??
      (header.toLowerCase() === "authorization" ? "Bearer " : "");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (key) headers[header] = prefix ? `${prefix.trimEnd()} ${key}` : key; // mis. "Bearer <kunci>"
    const n = Number(claim.pending ?? 1) || 1;
    const text = `Ada ${n} pesan chat baru dari staf untuk ${agentName} di Kantor Virtual Vertex8. ` +
      `Jalankan: python3 ${REPO}/agent-chat.py --agent ${agent} --pending  lalu balas tiap pesan dengan ` +
      `python3 ${REPO}/agent-chat.py --agent ${agent} --reply <id> --text "..."`;
    const payload = {
      event: "kv_chat_message", source: "kantor-virtual-vertex8", agent, agent_name: agentName,
      message_id: id, pending: n, sent_at: new Date().toISOString(), text, message: text, prompt: text,
    };
    try {
      const r = await fetch(url, { method: "POST", headers, body: JSON.stringify(payload), signal: AbortSignal.timeout(10000) });
      status = r.ok ? "dikirim" : `gagal_http_${r.status}`;
      await r.body?.cancel();
    } catch (_e) {
      status = "gagal_jaringan";
    }
  }
  try { await rpc("kv_chat_notify_done", { p_message_id: id, p_status: status }); } catch (e) {
    console.error("catat status gagal:", (e as Error).message);
  }
  console.log(`kv-chat-notify agent=${agent} status=${status}`); // tanpa URL/kunci/isi pesan
  return json({ ok: true, woke: status === "dikirim", reason: status });
});
