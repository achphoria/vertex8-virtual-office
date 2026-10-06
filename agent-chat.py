#!/usr/bin/env python3
"""Sisi agent untuk fitur "Ngobrol dengan Agent" di Kantor Virtual Vertex8.

Pakai (token penulis dibaca dari ~/.config/vertex8-office/writer_token atau env KV_WRITER_TOKEN):
  agent-chat.py --agent content --pending              # JSON pesan staf yang menunggu + riwayat singkat
  agent-chat.py --agent content --reply <id> --text "..."   # kirim balasan, tandai pesan (dan pesan
                                                       #   pending lebih lama di utas yang sama) terjawab
  agent-chat.py --agent content --reply <id> --text-file balasan.txt   # atau --text - (baca stdin)
  agent-chat.py --agent content --error <id> [--note "alasan singkat"]  # tandai gagal diproses

Status kantor: bila ada pesan, --pending memasang langkah "Membalas chat staf" (atau tugas kerja
"Membalas chat staf" bila agent sedang tidak kerja) lewat update-status.py. Setelah balasan terakhir
(tidak ada pesan pending lagi), tugas itu ditandai selesai. Isi chat TIDAK pernah ditulis ke status.
--no-status melewati pembaruan status. --step "..." mengganti teks langkah.
"""
import argparse, json, os, re, subprocess, sys
import urllib.error, urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
SB_URL = "https://ccbyqgisgclqlqatxwbk.supabase.co"
SB_KEY = "sb_publishable_pdEdMAYvBL4HUF9AMp1LaA_z0rbnXsY"  # kunci publik; penulisan dijaga token
TOKEN_FILE = os.path.expanduser("~/.config/vertex8-office/writer_token")
CHAT_TASK = "Membalas chat staf"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def die(msg, code=1):
    print(f"agent-chat: {msg}", file=sys.stderr)
    sys.exit(code)


def token():
    t = os.environ.get("KV_WRITER_TOKEN", "").strip()
    if t:
        return t
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
    except OSError:
        t = ""
    if not t:
        die(f"token penulis tidak ada ({TOKEN_FILE})", 3)
    return t


def rpc(name, args):
    body = json.dumps(args, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{SB_URL}/rest/v1/rpc/{name}", data=body, method="POST", headers={
        "apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
        "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(detail).get("message", detail)
        except Exception:
            pass
        die(f"{name} gagal (HTTP {e.code}): {detail}", 4)
    except (urllib.error.URLError, OSError, ValueError) as e:
        die(f"{name} gagal: {getattr(e, 'reason', e)}", 4)


def status(agent, mode, step_text, enabled):
    """mode: 'start' (ada pesan) atau 'done' (semua terjawab). Gagal di sini tidak menggagalkan chat."""
    if not enabled:
        return
    us = [sys.executable, os.path.join(REPO, "update-status.py"), "--agent", agent]
    def run(extra):
        r = subprocess.run(us + extra, capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()
    try:
        if mode == "start":
            code, out = run(["--step", step_text])
            if code != 0:  # agent belum kerja -> jadikan tugas kerja
                code, out = run(["--state", "working", "--task", CHAT_TASK, "--step", step_text])
        else:
            code, out = run(["--step", "Selesai membalas chat staf"])
            cur = current_task(agent)
            if cur == CHAT_TASK:
                code, out = run(["--state", "done", "--task", CHAT_TASK])
        if code != 0:
            print(f"agent-chat: PERINGATAN status kantor tidak diperbarui: {out[-200:]}", file=sys.stderr)
    except OSError as e:
        print(f"agent-chat: PERINGATAN status kantor: {e}", file=sys.stderr)


def current_task(agent):
    """Teks tugas 'Sekarang' agent dari Supabase (hanya baca)."""
    req = urllib.request.Request(f"{SB_URL}/rest/v1/kv_office_state?id=eq.1&select=data",
                                 headers={"apikey": SB_KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))[0]["data"]
    except Exception:
        return None
    key = agent.lower()
    for a in data.get("agents", []):
        if str(a.get("id", "")).lower() == key or str(a.get("name", "")).lower() == key:
            for t in a.get("tasks") or []:
                if str(t.get("status", "")).lower().startswith("sedang"):
                    return t.get("text")
    return None


def main():
    ap = argparse.ArgumentParser(description="Chat staf <-> agent Kantor Virtual Vertex8 (sisi agent).")
    ap.add_argument("--agent", required=True, help="id agent, mis. content")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pending", action="store_true", help="tampilkan pesan staf yang menunggu (JSON)")
    g.add_argument("--reply", metavar="MESSAGE_ID", help="balas pesan staf")
    g.add_argument("--error", metavar="MESSAGE_ID", help="tandai pesan gagal diproses")
    ap.add_argument("--text", help='isi balasan (pakai "-" untuk membaca stdin)')
    ap.add_argument("--text-file", help="baca isi balasan dari file")
    ap.add_argument("--note", default="", help="alasan singkat untuk --error (maks 200 karakter)")
    ap.add_argument("--limit", type=int, default=20, help="maks pesan pending (1-50)")
    ap.add_argument("--history", type=int, default=8, help="jumlah riwayat per pesan (0-30)")
    ap.add_argument("--step", default=CHAT_TASK, help=f'teks langkah status kantor (bawaan "{CHAT_TASK}")')
    ap.add_argument("--no-status", action="store_true", help="jangan ubah status kantor")
    a = ap.parse_args()

    agent = a.agent.strip().lower()
    if not ID_RE.match(agent):
        die("--agent tidak valid", 2)
    tok = token()

    if a.pending:
        res = rpc("kv_chat_pending", {"p_token": tok, "p_agent": agent, "p_limit": a.limit, "p_history": a.history})
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if res and res.get("count"):
            status(agent, "start", a.step, not a.no_status)
        return

    mid = (a.reply or a.error).strip()
    if not UUID_RE.match(mid):
        die("MESSAGE_ID harus uuid (lihat field id dari --pending)", 2)

    if a.reply:
        if a.text_file:
            with open(a.text_file, encoding="utf-8") as f:
                text = f.read()
        elif a.text == "-":
            text = sys.stdin.read()
        elif a.text is not None:
            text = a.text
        else:
            die("--reply butuh --text atau --text-file", 2)
        text = text.strip()
        if not text:
            die("balasan kosong", 2)
        if len(text) > 4000:
            die("balasan maks 4000 karakter", 2)
        res = rpc("kv_chat_reply", {"p_token": tok, "p_message_id": mid, "p_content": text})
    else:
        res = rpc("kv_chat_error", {"p_token": tok, "p_message_id": mid, "p_note": a.note[:200]})

    if res and res.get("agent") and res["agent"] != agent:
        print(f"agent-chat: PERINGATAN pesan ini milik agent '{res['agent']}'", file=sys.stderr)
    print(json.dumps(res, ensure_ascii=False))
    if res and res.get("pending_left") == 0:
        status(agent, "done", a.step, not a.no_status)


if __name__ == "__main__":
    main()
