#!/usr/bin/env python3
"""Perbarui status agen di Kantor Virtual Vertex8.

Alur: (1) tulis ke Supabase (halaman langsung berubah dalam hitungan detik lewat Realtime),
lalu (2) tulis status.json + commit + push ke GitHub sebagai cadangan.

Pakai (sama seperti sebelumnya):
  python3 /workspace/vertex8-virtual-office-repo/update-status.py \
      --agent "Mr. Wahyudi" --state working|scheduled|done --task "..." [--next "..."] [--output "..."]

state:
  working   -> tugas "Sekarang" (Sedang kerja) diganti dengan --task
  scheduled -> agen tidak sedang kerja; --task jadi tugas "Berikutnya" (Terjadwal)
  done      -> tugas kerja dihapus; --task jadi "Baru selesai" (Selesai)
--next      -> (opsional) ganti tugas "Berikutnya" (Terjadwal)
--output    -> (opsional) hasil/keluaran singkat terakhir (field last_output, maks 280 karakter).
               Boleh dipakai sendiri tanpa --state/--task:  --agent grok --output "..."
Tugas berlabel lain (mis. "Rutin") tidak disentuh.

Langkah kecil (sering & murah, HANYA ke Supabase, tanpa commit git):
  update-status.py --agent grok --step "lagi query data"
  -> tampil di gelembung/panel sebagai "↳ lagi query data" pada tugas "Sekarang".
     Butuh agen yang sedang kerja (atau gabungkan: --state working --task "..." --step "...").
     --state apa pun mengganti tugas "Sekarang" sehingga langkah lama otomatis hilang.

Kolaborasi / rapat (agen pindah ke Ruang Meeting di halaman bila 2+ agen bekerja bersama):
  update-status.py --agent analyst --state working --task "Susun rencana promo" --with marketing,content
  update-status.py --agent analyst --meeting "Rencana promo bulan depan" [--with marketing]
  update-status.py --agent analyst --end-meeting          # selesai rapat, kembali ke meja
  --with      -> id/nama agen lain dipisah koma (diri sendiri diabaikan). Rekan yang tidak sedang kerja
                 tetap ikut dipanggil ke ruang meeting di halaman.
  --meeting   -> topik rapat singkat (maks 80 karakter; aturan teks sama: tanpa Rp/angka member/no. HP).
                 Dua agen yang sedang kerja dengan topik --meeting sama juga dianggap satu rapat.
  Disimpan di tugas "Sekarang", jadi butuh agen yang sedang kerja (atau --state working). --state apa pun
  yang baru (termasuk done) otomatis mengakhiri rapat.

Daftarkan / hapus bot (kantor punya 9 meja divisi, 3x3):
  update-status.py --add-agent --agent <id> --name "Nama Bot" [--role "Peran"] [--desk 1-9] [--state ... --task ...]
  update-status.py --remove-agent --agent <id|nama>
  --desk N   -> (opsional) nomor meja 1..9 (01 Builder, 02 Ops & Data, 03 Marketing, 04 Member Success,
                05 Performance, 06 Finance, 07 Content & Creative, 08 HR & People, 09 Engineering & Facility).
                Tanpa --desk, agen baru otomatis dapat meja kosong pertama. Untuk agen yang sudah ada,
                --add-agent --agent <id> --name "..." --desk N memindahkan mejanya (meja harus kosong).

Keluar 0 bila minimal satu tujuan (Supabase atau GitHub) berhasil; peringatan dicetak bila
salah satu gagal. --step keluar non-zero bila Supabase gagal. JANGAN masukkan angka bisnis:
teks berisi "Rp", "<angka> member", atau nomor telepon akan ditolak.
Token penulis Supabase dibaca dari ~/.config/vertex8-office/writer_token (atau env KV_WRITER_TOKEN).
"""
import argparse, datetime, fcntl, json, os, re, subprocess, sys, time
import urllib.error, urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(REPO, "status.json")
LOG_MAX = 20
OUTPUT_MAX = 280
MAX_AGENTS = 12
DESKS = 9  # grid meja 3x3 di halaman
DEFAULT_ROLE = "Asisten AI"
STEP_MAX = 120
MEETING_MAX = 80
# Supabase (proyek "General Table"); URL + kunci publishable memang publik.
# Penulisan dilindungi token rahasia yang dicek oleh fungsi kv_set_state.
SB_URL = "https://ccbyqgisgclqlqatxwbk.supabase.co"
SB_KEY = "sb_publishable_pdEdMAYvBL4HUF9AMp1LaA_z0rbnXsY"
SB_TOKEN_FILE = os.path.expanduser("~/.config/vertex8-office/writer_token")
SB_TIMEOUT = 8
STATE_MAP = {
    "working":   ("Sedang kerja", "Sekarang"),
    "scheduled": ("Terjadwal", "Berikutnya"),
    "done":      ("Selesai", "Baru selesai"),
}
BLOCK = [
    (re.compile(r"Rp"), "mengandung 'Rp'"),
    (re.compile(r"\brp\s*\d", re.I), "mengandung 'rp' + angka"),
    (re.compile(r"\d[\d.,\s]*member", re.I), "mengandung angka + 'member'"),
    (re.compile(r"(\+62|\b62|\b0)8\d[\d\s-]{6,}"), "mirip nomor telepon"),
]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def die(msg, code=1):
    print(f"update-status: {msg}", file=sys.stderr)
    sys.exit(code)


def git(*args, check=True):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} gagal:\n{r.stdout}{r.stderr}", 3)
    return r


def guard(label, text):
    if text is None:
        return
    for rx, why in BLOCK:
        if rx.search(text):
            die(f"--{label} ditolak ({why}); jangan publikasikan angka bisnis/data pribadi.", 2)


def now_wib():
    tz = datetime.timezone(datetime.timedelta(hours=7))
    return datetime.datetime.now(tz).replace(microsecond=0).isoformat()


def warn(msg):
    print(f"update-status: PERINGATAN: {msg}", file=sys.stderr)


def sb_token():
    t = os.environ.get("KV_WRITER_TOKEN", "").strip()
    if t:
        return t
    try:
        with open(SB_TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def sb_request(method, path, body=None):
    headers = {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(SB_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=SB_TIMEOUT) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(detail).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(str(getattr(e, "reason", e))) from None


def sb_read():
    """Dokumen terkini dari Supabase, atau None bila gagal/kosong."""
    try:
        rows = sb_request("GET", "/rest/v1/kv_office_state?id=eq.1&select=data")
    except RuntimeError as e:
        warn(f"gagal membaca Supabase ({e}); pakai status.json lokal")
        return None
    if isinstance(rows, list) and rows and isinstance(rows[0].get("data"), dict) \
            and isinstance(rows[0]["data"].get("agents"), list):
        return rows[0]["data"]
    return None


def sb_write(doc):
    """Tulis seluruh dokumen ke Supabase. Kembalikan None bila sukses, atau pesan error."""
    tok = sb_token()
    if not tok:
        return f"token penulis tidak ada ({SB_TOKEN_FILE})"
    try:
        sb_request("POST", "/rest/v1/rpc/kv_set_state", {"p_token": tok, "p_data": doc})
        return None
    except RuntimeError as e:
        return str(e)


def ts_of(doc):
    try:
        return datetime.datetime.fromisoformat(str(doc.get("updated_at", "")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def read_local():
    try:
        with open(STATUS, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def ordered_doc(data, ts):
    data.pop("updated", None)
    data["updated_at"] = ts
    # urutkan kunci supaya updated_at tetap dekat atas
    ordered = {"office": data.get("office", "Vertex8 HQ"), "updated_at": ts}
    ordered.update({k: v for k, v in data.items() if k not in ordered})
    return ordered


def ststate(status):
    s = (status or "").lower()
    return "work" if s.startswith("sedang") else "sched" if s.startswith("terjad") else "done" if s.startswith("selesai") else "work"


def find_agent(agents, key):
    key = key.strip().lower()
    return next((x for x in agents if str(x.get("name", "")).lower() == key or str(x.get("id", "")).lower() == key), None)


def desk_of(ag):
    d = ag.get("desk")
    return d if isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= DESKS else None


def effective_desks(agents):
    """Sama dengan aturan halaman: meja eksplisit dulu, agen tanpa meja mengisi meja kosong berurutan."""
    res, used = {}, set()
    for x in agents:
        d = desk_of(x)
        if d is not None and d not in used:
            res[id(x)] = d
            used.add(d)
    for x in agents:
        if id(x) not in res:
            d = next((n for n in range(1, DESKS + 1) if n not in used), None)
            if d is not None:
                res[id(x)] = d
                used.add(d)
    return res


def free_desk(agents):
    used = set(effective_desks(agents).values())
    return next((n for n in range(1, DESKS + 1) if n not in used), None)


def add_log(data, ts, name, status, text):
    log = data.get("log") if isinstance(data.get("log"), list) else []
    log.insert(0, {"t": ts, "agent": name, "status": status, "text": text})
    data["log"] = log[:LOG_MAX]


def apply_state(ag, state, task, nxt):
    status, label = STATE_MAP[state]
    tasks = ag.get("tasks") or []
    work = [t for t in tasks if ststate(t.get("status")) == "work"]
    nexts = [t for t in tasks if ststate(t.get("status")) == "sched" and t.get("label", "Berikutnya") == "Berikutnya"]
    dones = [t for t in tasks if ststate(t.get("status")) == "done"]
    other = [t for t in tasks if t not in work and t not in nexts and t not in dones]  # mis. "Rutin"

    if state == "working":
        work = [{"status": status, "label": label, "text": task}]
    elif state == "scheduled":
        work = []
        nexts = [{"status": status, "label": label, "text": task}]
    else:  # done
        work = []
        dones = [{"status": status, "label": label, "text": task}]
    if nxt:
        if state == "scheduled":
            nexts.append({"status": "Terjadwal", "label": "Berikutnya", "text": nxt})
        else:
            nexts = [{"status": "Terjadwal", "label": "Berikutnya", "text": nxt}]
    ag["tasks"] = work + nexts + dones[:1] + other
    return status


def write_status(data, ts):
    ordered = ordered_doc(data, ts)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, STATUS)


def git_publish(mutate, no_push, doc_after=None):
    """pull -> ubah status.json -> commit -> push. Kembalikan True bila sukses.
    doc_after: bila Supabase sudah ditulis, status.json disamakan dengan dokumen terbaru di Supabase
    (dibaca ulang tiap percobaan). Bila None, mutate diterapkan ke status.json hasil pull (cara lama).
    Bila push ditolak (ada commit baru di remote), commit kita dibuang lalu diulang (tanpa konflik rebase)."""
    for attempt in range(1, 4):
        r = git("pull", "--rebase", "--autostash", "--quiet", "origin", "main", check=False)
        if r.returncode != 0:
            warn(f"git pull gagal (percobaan {attempt}): {(r.stdout + r.stderr).strip()[:300]}")
            git("rebase", "--abort", check=False)
            time.sleep(2 * attempt)
            continue
        if doc_after is not None:
            data = doc_after(attempt)
            msg = data.pop("__msg__")
            ts = data.get("updated_at") or now_wib()
        else:
            data = read_local()
            if data is None:
                warn("status.json tidak terbaca")
                return False
            if not isinstance(data.get("agents"), list):
                data["agents"] = []
            ts = now_wib()
            msg = mutate(data, ts)
        write_status(data, ts)
        git("add", "status.json", check=False)
        if not git("diff", "--cached", "--quiet", check=False).returncode:
            print("GitHub: status.json sudah sama, tidak ada commit baru")
            return True
        msg = msg if len(msg) <= 100 else msg[:99] + "…"
        r = git("commit", "--quiet", "-m", msg, check=False)
        if r.returncode != 0:
            warn(f"git commit gagal: {(r.stdout + r.stderr).strip()[:300]}")
            git("reset", "--quiet", "HEAD", "--", "status.json", check=False)
            git("checkout", "--", "status.json", check=False)
            return False
        if no_push:
            print(f"OK (lokal, tanpa push): {msg}")
            return True
        r = git("push", "--quiet", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"GitHub OK {sha}: {msg}")
            return True
        warn(f"push gagal (percobaan {attempt}): {r.stderr.strip()}")
        git("reset", "--quiet", "--keep", "HEAD~1")  # buang commit kita saja; file lain tidak disentuh
        time.sleep(2 * attempt)
    warn("push ke GitHub gagal setelah 3 percobaan.")
    return False


def base_doc():
    """Dokumen dasar: Supabase (paling baru) atau status.json lokal bila lebih baru / Supabase gagal."""
    sb = sb_read()
    loc = read_local()
    if sb is not None and loc is not None:
        a, b = ts_of(sb), ts_of(loc)
        if a and b and b > a and isinstance(loc.get("agents"), list):
            return loc, "lokal (lebih baru dari Supabase)"
        return sb, "supabase"
    if sb is not None:
        return sb, "supabase"
    return None, "lokal"


def run_update(mutate, no_push, use_sb=True):
    """Supabase dulu (supaya halaman berubah dalam hitungan detik), lalu GitHub sebagai cadangan."""
    sb_ok = False
    pushed_doc = None
    if use_sb and not no_push:
        base, src = base_doc()
        if base is not None:
            data = json.loads(json.dumps(base))
            if not isinstance(data.get("agents"), list):
                data["agents"] = []
            ts = now_wib()
            msg = mutate(data, ts)
            doc = ordered_doc(data, ts)
            err = sb_write(doc)
            if err is None:
                sb_ok = True
                pushed_doc = (doc, msg)
                print(f"Supabase OK: {msg}")
            else:
                warn(f"gagal menulis ke Supabase: {err}")
        else:
            warn("Supabase tidak terbaca; lanjut ke GitHub saja")

    if sb_ok:
        def doc_after(attempt):
            doc, msg = pushed_doc
            if attempt > 1:  # retry: pakai versi Supabase terbaru
                latest = sb_read()
                if latest is not None:
                    doc = latest
            d = json.loads(json.dumps(doc))
            d["__msg__"] = msg
            return d
        gh_ok = git_publish(mutate, no_push, doc_after)
    else:
        gh_ok = git_publish(mutate, no_push)

    if sb_ok and not gh_ok:
        warn("tersimpan di Supabase (halaman sudah berubah), tapi cadangan GitHub gagal.")
    if not sb_ok and not gh_ok:
        die("gagal menyimpan ke Supabase maupun GitHub (tidak ada perubahan yang tersimpan).", 4)


def run_step(agent_key, step, ts):
    """Hanya Supabase: set field 'step' pada tugas "Sekarang" milik agen."""
    data = sb_read()
    if data is None:
        die("--step butuh Supabase, tapi Supabase tidak terbaca (langkah tidak disimpan).", 5)
    ag = find_agent(data["agents"], agent_key)
    if ag is None:
        die(f"agen '{agent_key}' tidak ditemukan. Pilihan: " + ", ".join(x.get("name", "?") for x in data["agents"]), 2)
    work = next((t for t in (ag.get("tasks") or []) if ststate(t.get("status")) == "work"), None)
    if work is None:
        die(f"{ag.get('name')} tidak sedang kerja; pakai dulu --state working --task \"...\" (boleh sekalian --step).", 2)
    work["step"] = step
    work["step_at"] = ts
    err = sb_write(ordered_doc(data, ts))
    if err is not None:
        die(f"gagal menulis langkah ke Supabase: {err}", 5)
    print(f"Supabase OK: langkah {ag.get('name')} -> {step}")


def main():
    ap = argparse.ArgumentParser(description="Perbarui status agen Kantor Virtual Vertex8 (Supabase realtime + cadangan GitHub).")
    ap.add_argument("--agent", help='nama atau id agen, mis. "Mr. Wahyudi" (untuk --add-agent: id baru, mis. "designer")')
    ap.add_argument("--state", choices=list(STATE_MAP))
    ap.add_argument("--task")
    ap.add_argument("--next", dest="nxt", default=None, help='tugas "Berikutnya" (opsional)')
    ap.add_argument("--output", default=None, help=f"hasil/keluaran singkat terakhir (opsional, maks {OUTPUT_MAX} karakter)")
    ap.add_argument("--add-agent", action="store_true", help="daftarkan bot baru (butuh --agent <id> dan --name)")
    ap.add_argument("--remove-agent", action="store_true", help="hapus bot (butuh --agent <id|nama>)")
    ap.add_argument("--name", help="nama tampilan bot (untuk --add-agent)")
    ap.add_argument("--role", help=f'peran bot (untuk --add-agent, bawaan "{DEFAULT_ROLE}")')
    ap.add_argument("--desk", type=int, default=None, help=f"nomor meja 1..{DESKS} (untuk --add-agent; bawaan: meja kosong pertama)")
    ap.add_argument("--step", default=None, help=f'langkah kecil yang sedang dikerjakan (maks {STEP_MAX} karakter); hanya ke Supabase, tanpa commit')
    ap.add_argument("--with", dest="with_", default=None, help='rekan kolaborasi: id/nama agen dipisah koma, mis. "marketing,content"')
    ap.add_argument("--meeting", default=None, help=f'topik rapat singkat (maks {MEETING_MAX} karakter)')
    ap.add_argument("--end-meeting", action="store_true", help="akhiri rapat/kolaborasi (hapus --with/--meeting)")
    ap.add_argument("--no-push", action="store_true", help="hanya ubah + commit lokal, tanpa Supabase (untuk uji)")
    ap.add_argument("--no-supabase", action="store_true", help="lewati Supabase, hanya GitHub (cara lama)")
    a = ap.parse_args()

    if a.add_agent and a.remove_agent:
        die("pilih salah satu: --add-agent atau --remove-agent", 2)
    if not a.agent or not a.agent.strip():
        die("--agent wajib diisi", 2)
    task = a.task.strip() if a.task is not None else None
    nxt = a.nxt.strip() if a.nxt else None
    out = a.output.strip() if a.output is not None else None
    name = a.name.strip() if a.name else None
    role = a.role.strip() if a.role else None
    step = a.step.strip() if a.step is not None else None
    if a.step is not None:
        if not step:
            die("--step kosong", 2)
        step = " ".join(step.split())
        if len(step) > STEP_MAX:
            step = step[:STEP_MAX - 1].rstrip() + "…"
        if a.add_agent or a.remove_agent:
            die("--step tidak bisa digabung dengan --add-agent/--remove-agent", 2)
        if a.state is not None and a.state != "working":
            die("--step hanya bisa digabung dengan --state working", 2)
        if a.no_supabase:
            die("--step butuh Supabase (jangan pakai --no-supabase)", 2)

    meeting = " ".join(a.meeting.split()) if a.meeting is not None else None
    with_raw = [x.strip() for x in a.with_.split(",") if x.strip()] if a.with_ is not None else None
    collab = with_raw is not None or meeting is not None or a.end_meeting
    if a.meeting is not None and not meeting:
        die("--meeting kosong", 2)
    if meeting and len(meeting) > MEETING_MAX:
        meeting = meeting[:MEETING_MAX - 1].rstrip() + "…"
    if a.with_ is not None and not with_raw:
        die("--with kosong (isi id/nama agen dipisah koma)", 2)
    if with_raw and len(with_raw) > 8:
        die("--with maksimal 8 agen", 2)
    if collab:
        if a.add_agent or a.remove_agent:
            die("--with/--meeting/--end-meeting tidak bisa digabung dengan --add-agent/--remove-agent", 2)
        if a.end_meeting and (with_raw is not None or meeting is not None):
            die("--end-meeting tidak bisa digabung dengan --with/--meeting", 2)
        if a.state is not None and a.state != "working" and not a.end_meeting:
            die("--with/--meeting hanya untuk agen yang sedang kerja (--state working)", 2)
    if a.task is not None and not task:
        die("--task kosong", 2)
    if (a.state is None) != (task is None):
        die("--state dan --task harus dipakai bersama", 2)
    if out is not None:
        if not out:
            die("--output kosong", 2)
        if len(out) > OUTPUT_MAX:
            out = out[:OUTPUT_MAX - 1].rstrip() + "…"
    if a.desk is not None:
        if not a.add_agent:
            die("--desk hanya untuk --add-agent", 2)
        if not 1 <= a.desk <= DESKS:
            die(f"--desk harus 1..{DESKS}", 2)
    if a.remove_agent and (task or nxt or out or name or role):
        die("--remove-agent tidak bisa digabung dengan opsi lain", 2)
    if not a.add_agent and not a.remove_agent:
        if task is None and out is None and step is None and not collab:
            die("butuh --state + --task (atau --output / --step / --with / --meeting saja)", 2)
        if nxt and task is None:
            die("--next harus dipakai bersama --state dan --task", 2)
        if name or role:
            die("--name/--role hanya untuk --add-agent", 2)
    if a.add_agent:
        if not ID_RE.match(a.agent.strip()):
            die("id agen untuk --add-agent harus huruf kecil/angka/-/_ (maks 32), mis. \"designer\"", 2)
        if not name:
            die("--add-agent butuh --name", 2)
        if len(name) > 40 or (role and len(role) > 40):
            die("--name/--role maksimal 40 karakter", 2)
    for label, val in (("task", task), ("next", nxt), ("output", out), ("name", name), ("role", role), ("step", step), ("meeting", meeting)):
        guard(label, val)

    # kunci agar beberapa bot tidak bentrok
    lockf = open(os.path.join(REPO, ".git", "update-status.lock"), "w")
    fcntl.flock(lockf, fcntl.LOCK_EX)

    # ---- mode langkah saja: cepat, hanya Supabase ----
    if step is not None and task is None and out is None and not collab:
        if a.no_push:
            print(f"OK (uji, tanpa Supabase): langkah {a.agent} -> {step}")
            return
        run_step(a.agent, step, now_wib())
        return

    def mutate(data, ts):
        agents = data["agents"]
        # ---- hapus agen ----
        if a.remove_agent:
            ag = find_agent(agents, a.agent)
            if ag is None:
                die(f"agen '{a.agent}' tidak ditemukan. Pilihan: " + ", ".join(x.get("name", "?") for x in agents), 2)
            if len(agents) <= 1:
                die("tidak bisa menghapus agen terakhir", 2)
            agents.remove(ag)
            add_log(data, ts, ag.get("name"), "Info", "Keluar dari kantor")
            return f"agent: hapus {ag.get('name')} ({ag.get('id')})"

        msgs = []
        # ---- tambah / perbarui agen ----
        if a.add_agent:
            aid = a.agent.strip()
            ag = next((x for x in agents if str(x.get("id", "")).lower() == aid), None)
            clash = find_agent(agents, name)
            if clash is not None and clash is not ag:
                die(f"nama '{name}' sudah dipakai agen lain ({clash.get('id')})", 2)
            if a.desk is not None:
                owner = next((x for x in agents if x is not ag and desk_of(x) == a.desk), None)
                if owner is not None:
                    die(f"meja {a.desk} sudah dipakai {owner.get('name')} ({owner.get('id')})", 2)
            if ag is None:
                if len(agents) >= MAX_AGENTS:
                    die(f"maksimal {MAX_AGENTS} agen", 2)
                ag = {"id": aid, "name": name, "role": role or DEFAULT_ROLE, "tasks": []}
                desk = a.desk if a.desk is not None else free_desk(agents)
                if desk is not None:
                    ag["desk"] = desk
                agents.append(ag)
                add_log(data, ts, name, "Info", f"Bergabung ke kantor sebagai {ag['role']}")
                msgs.append(f"agent: tambah {name} ({aid})" + (f" meja {desk}" if desk else ""))
            else:
                ag["name"] = name
                if role:
                    ag["role"] = role
                if a.desk is not None:
                    ag["desk"] = a.desk
                msgs.append(f"agent: perbarui {name} ({aid})" + (f" meja {a.desk}" if a.desk is not None else ""))
        else:
            ag = find_agent(agents, a.agent)
            if ag is None:
                die(f"agen '{a.agent}' tidak ditemukan. Pilihan: " + ", ".join(x.get("name", "?") for x in agents), 2)

        if task is not None:
            status = apply_state(ag, a.state, task, nxt)  # tugas baru -> langkah lama ikut hilang
            add_log(data, ts, ag.get("name"), status, task)
            msgs.append(f"status: {ag.get('name')} {a.state} - {task}")
            if step is not None and a.state == "working":
                ag["tasks"][0]["step"] = step
                ag["tasks"][0]["step_at"] = ts
        if step is not None and task is None:  # mis. --output + --step
            work = next((t for t in (ag.get("tasks") or []) if ststate(t.get("status")) == "work"), None)
            if work is None:
                die(f"{ag.get('name')} tidak sedang kerja; --step butuh tugas \"Sekarang\".", 2)
            work["step"] = step
            work["step_at"] = ts
        if collab:
            work = next((t for t in (ag.get("tasks") or []) if ststate(t.get("status")) == "work"), None)
            if a.end_meeting:
                if work is not None and (work.pop("with", None) is not None) | (work.pop("meeting", None) is not None):
                    add_log(data, ts, ag.get("name"), "Info", "Rapat selesai, kembali ke meja")
                    msgs.append(f"rapat: {ag.get('name')} selesai")
                elif task is None:
                    print(f"Info: {ag.get('name')} tidak sedang rapat.")
            else:
                if work is None:
                    die(f"{ag.get('name')} tidak sedang kerja; --with/--meeting butuh tugas \"Sekarang\" "
                        "(gabungkan dengan --state working --task \"...\").", 2)
                before = (list(work.get("with") or []), work.get("meeting"))
                if with_raw is not None:
                    ids = []
                    for key in with_raw:
                        other = find_agent(agents, key)
                        if other is None:
                            die(f"--with: agen '{key}' tidak ditemukan. Pilihan: " +
                                ", ".join(str(x.get("id", "?")) for x in agents), 2)
                        oid = str(other.get("id") or "")
                        if other is not ag and oid and oid not in ids:
                            ids.append(oid)
                    if not ids and meeting is None:
                        die("--with hanya berisi diri sendiri; sebutkan agen lain", 2)
                    work["with"] = ids
                if meeting is not None:
                    work["meeting"] = meeting
                after = (list(work.get("with") or []), work.get("meeting"))
                if after != before:
                    names = [str((find_agent(agents, i) or {}).get("name", i)) for i in after[0]]
                    txt = "Rapat" + (" dengan " + ", ".join(names) if names else "") + (f": {after[1]}" if after[1] else "")
                    add_log(data, ts, ag.get("name"), "Info", txt[:400])
                    msgs.append(f"rapat: {ag.get('name')} " + ",".join(after[0]) + (f" - {after[1]}" if after[1] else ""))
        if out is not None:
            ag["last_output"] = out
            ag["last_output_at"] = ts
            if task is None:
                msgs.append(f"status: {ag.get('name')} output")
        return " | ".join(reversed(msgs))

    run_update(mutate, a.no_push, use_sb=not a.no_supabase)


if __name__ == "__main__":
    main()
