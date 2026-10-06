#!/usr/bin/env python3
"""Kelola allowlist staf untuk fitur "Ngobrol dengan Agent" (Kantor Virtual Vertex8).

Token admin dibaca dari ~/.config/vertex8-office/admin_token (atau env KV_ADMIN_TOKEN); DB hanya
menyimpan hash sha256-nya. Jangan pernah commit/print token.

  staff-admin.py list
  staff-admin.py add --email nama@contoh.com --name "Nama Staf" [--agents all|content,marketing] [--admin]
  staff-admin.py update --email nama@contoh.com [--name ...] [--agents all|content,marketing] [--admin|--no-admin]
  --agents all  -> boleh ngobrol dengan SEMUA agent yang aktif (termasuk agent baru nanti). Bawaan `add`: all.
                   Admin selalu boleh ngobrol dengan semua agent.
  staff-admin.py disable --email nama@contoh.com     # cabut akses (riwayat chat tetap ada)
  staff-admin.py enable  --email nama@contoh.com
  staff-admin.py remove  --email nama@contoh.com     # hapus dari allowlist
  staff-admin.py rotate-token                        # buat token admin baru (yang lama tidak berlaku)

Akun login (email + sandi) dibuat pemilik di Supabase Dashboard:
  Authentication > Users > Add user > Create new user (isi email + sandi, centang "Auto Confirm User").
Urutan bebas: bila akun dibuat setelah `add`, akses tersambung otomatis saat staf pertama kali login.
"""
import argparse, hashlib, json, os, secrets, sys
import urllib.error, urllib.request

SB_URL = "https://ccbyqgisgclqlqatxwbk.supabase.co"
SB_KEY = "sb_publishable_pdEdMAYvBL4HUF9AMp1LaA_z0rbnXsY"
TOKEN_FILE = os.path.expanduser("~/.config/vertex8-office/admin_token")


def die(msg, code=1):
    print(f"staff-admin: {msg}", file=sys.stderr)
    sys.exit(code)


def token():
    t = os.environ.get("KV_ADMIN_TOKEN", "").strip()
    if not t:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                t = f.read().strip()
        except OSError:
            die(f"token admin tidak ada ({TOKEN_FILE})", 3)
    return t


def call(args):
    body = json.dumps(args).encode("utf-8")
    req = urllib.request.Request(f"{SB_URL}/rest/v1/rpc/kv_staff_admin", data=body, method="POST", headers={
        "apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        d = e.read().decode("utf-8", "replace")[:300]
        try:
            d = json.loads(d).get("message", d)
        except Exception:
            pass
        die(f"gagal (HTTP {e.code}): {d}", 4)
    except (urllib.error.URLError, OSError) as e:
        die(f"gagal: {getattr(e, 'reason', e)}", 4)


def agents_txt(lst):
    lst = list(lst or [])
    if "*" in lst:
        return "semua"
    return ", ".join(lst) or "-"


def show(row):
    if not isinstance(row, dict):
        print(json.dumps(row, ensure_ascii=False))
        return
    flags = ("AKTIF" if row.get("active") else "NONAKTIF") + (" · ADMIN" if row.get("is_admin") else "")
    acct = ("akun login ada" + ("" if row.get("auth_confirmed") else " (BELUM terkonfirmasi)")) if row.get("auth_user") \
        else "akun login BELUM dibuat"
    print(f"- {row.get('email')}  \"{row.get('display_name')}\"  [{flags}]  agent: {agents_txt(row.get('allowed_agents'))}"
          f"  · {acct}{' · tersambung' if row.get('linked') else ''}")
    if not row.get("auth_user"):
        print("  -> Buat akun: Supabase Dashboard > Authentication > Users > Add user > Create new user "
              "(email ini + sandi, centang Auto Confirm User). Lalu staf masuk lewat tombol 'Masuk' di situs.")


def main():
    ap = argparse.ArgumentParser(description="Kelola allowlist staf chat Kantor Virtual Vertex8.")
    ap.add_argument("action", choices=["list", "add", "update", "disable", "enable", "remove", "rotate-token"])
    ap.add_argument("--email")
    ap.add_argument("--name", help="nama tampilan staf")
    ap.add_argument("--agents", help='"all" (semua agent) atau daftar id agent dipisah koma (bawaan add: all)')
    ap.add_argument("--admin", dest="admin", action="store_true", default=None)
    ap.add_argument("--no-admin", dest="admin", action="store_false")
    a = ap.parse_args()
    tok = token()

    if a.action == "list":
        rows = call({"p_token": tok, "p_action": "list"})
        if not rows:
            print("Allowlist kosong. Tambah staf: staff-admin.py add --email ... --name \"...\"")
        for r in rows or []:
            show(r)
        return
    if a.action == "rotate-token":
        new = secrets.token_urlsafe(32)
        call({"p_token": tok, "p_action": "rotate_token", "p_display_name": hashlib.sha256(new.encode()).hexdigest()})
        if not os.environ.get("KV_ADMIN_TOKEN"):
            old_umask = os.umask(0o077)
            try:
                with open(TOKEN_FILE + ".tmp", "w", encoding="utf-8") as f:
                    f.write(new + "\n")
                os.replace(TOKEN_FILE + ".tmp", TOKEN_FILE)
                os.chmod(TOKEN_FILE, 0o600)
            finally:
                os.umask(old_umask)
            print(f"Token admin baru tersimpan di {TOKEN_FILE} (chmod 600).")
        else:
            print("Token admin diganti, tapi KV_ADMIN_TOKEN dipakai: simpan token baru secara manual.", file=sys.stderr)
            print(new)
        return

    if not a.email:
        die("--email wajib", 2)
    agents = None
    if a.agents is not None:
        agents = [x.strip().lower() for x in a.agents.split(",") if x.strip()]
        if any(x in ("all", "*", "semua") for x in agents):
            agents = ["*"]
    if a.action in ("add", "update"):
        if a.action == "add" and agents is None:
            agents = ["*"]
        row = call({"p_token": tok, "p_action": "upsert", "p_email": a.email, "p_display_name": a.name,
                    "p_allowed": agents, "p_is_admin": a.admin if a.action == "update" else bool(a.admin)})
        show(row)
    elif a.action in ("disable", "enable"):
        show(call({"p_token": tok, "p_action": a.action, "p_email": a.email}))
    elif a.action == "remove":
        print(json.dumps(call({"p_token": tok, "p_action": "remove", "p_email": a.email}), ensure_ascii=False))


if __name__ == "__main__":
    main()
