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
// Agent "content" juga menerima nama lama tanpa akhiran (WEBHOOK_URL / WEBHOOK_KEY) agar kompatibel.
// Bila URL belum diset, pesan tetap "pending" (wake_status = belum_dikonfigurasi) dan staf melihat catatan
// "Agent ini belum tersambung…" — pesan tidak hilang dan akan dibalas setelah agent tersambung.
// GET ?status=1 → {"ok":true,"agents":{"analyst":false,...}}: HANYA boolean "sudah tersambung" per agent
// (tanpa URL/kunci) untuk ikon steker di web.
// Isi chat TIDAK pernah dikirim ke webhook; agent mengambilnya sendiri lewat agent-chat.py.

const SB_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const REPO = "/workspace/vertex8-virtual-office-repo";

const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "apikey, authorization, content-type" };
function json(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...extra } });
}
function suffix(agent: string): string { return agent.toUpperCase().replace(/[^A-Z0-9]/g, "_"); }
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
function hookUrl(agent: string): string | undefined {
  const suf = suffix(agent);
  return env(`WEBHOOK_URL_${suf}`) || (agent === "content" ? env("WEBHOOK_URL") : undefined) || undefined;
}
function hookKey(agent: string): string | undefined {
  const suf = suffix(agent);
  return env(`WEBHOOK_KEY_${suf}`) || (agent === "content" ? env("WEBHOOK_KEY") : undefined) || undefined;
}
async function connStatus(): Promise<Response> {
  const agents: Record<string, boolean> = {};
  try {
    const r = await fetch(`${SB_URL}/rest/v1/kv_chat_agents?select=agent,enabled`, {
      headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    for (const row of (await r.json()) as Array<{ agent: string; enabled: boolean }>) {
      if (/^[a-z0-9_-]{1,32}$/.test(row.agent)) agents[row.agent] = !!row.enabled && !!hookUrl(row.agent);
    }
  } catch (e) {
    console.error("status gagal:", (e as Error).message);
    return json({ ok: false }, 500, CORS);
  }
  return json({ ok: true, agents }, 200, { ...CORS, "Cache-Control": "public, max-age=60" });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (req.method === "GET") return SB_URL && SERVICE_KEY ? await connStatus() : json({ ok: false }, 500, CORS);
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
  const suf = suffix(agent);
  const url = hookUrl(agent);
  const key = hookKey(agent);
  let status = "belum_dikonfigurasi";

  if (url) {
    const header = env(`WEBHOOK_AUTH_HEADER_${suf}`) || env("WEBHOOK_AUTH_HEADER") || "Authorization";
    const prefix = env(`WEBHOOK_AUTH_PREFIX_${suf}`) ?? env("WEBHOOK_AUTH_PREFIX") ??
      (header.toLowerCase() === "authorization" ? "Bearer " : "");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (key) headers[header] = prefix ? `${prefix.trimEnd()} ${key}` : key; // mis. "Bearer <kunci>"
    const n = Number(claim.pending ?? 1) || 1;
    const text = `Ada ${n} pesan chat baru dari staf untuk ${agentName} (agent "${agent}") di Kantor Virtual Vertex8. ` +
      `Jalankan: python3 ${REPO}/agent-chat.py --agent ${agent} --pending  lalu balas tiap pesan dengan ` +
      `python3 ${REPO}/agent-chat.py --agent ${agent} --reply <id> --text-file <file>  ` +
      `(bila gagal: --error <id> --note "..."). Ikuti prompt routine agent ini.`;
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
