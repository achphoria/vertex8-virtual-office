#!/usr/bin/env python3
"""Perbarui status agen di Kantor Virtual Vertex8 (status.json) lalu push ke GitHub.

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

Daftarkan / hapus bot (kantor otomatis menambah meja & robot pixel baru):
  update-status.py --add-agent --agent <id> --name "Nama Bot" [--role "Peran"] [--state ... --task ...]
  update-status.py --remove-agent --agent <id|nama>

Keluar non-zero bila gagal (termasuk gagal push). JANGAN masukkan angka bisnis:
teks berisi "Rp", "<angka> member", atau nomor telepon akan ditolak.
"""
import argparse, datetime, fcntl, json, os, re, subprocess, sys, time

REPO = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(REPO, "status.json")
LOG_MAX = 20
OUTPUT_MAX = 280
MAX_AGENTS = 12
DEFAULT_ROLE = "Asisten AI"
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


def ststate(status):
    s = (status or "").lower()
    return "work" if s.startswith("sedang") else "sched" if s.startswith("terjad") else "done" if s.startswith("selesai") else "work"


def find_agent(agents, key):
    key = key.strip().lower()
    return next((x for x in agents if str(x.get("name", "")).lower() == key or str(x.get("id", "")).lower() == key), None)


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
    data.pop("updated", None)
    data["updated_at"] = ts
    # urutkan kunci supaya updated_at tetap dekat atas
    ordered = {"office": data.get("office", "Vertex8 HQ"), "updated_at": ts}
    ordered.update({k: v for k, v in data.items() if k not in ordered})
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, STATUS)


def run_update(mutate, no_push):
    """pull -> ubah status.json -> commit -> push. Bila push ditolak (ada commit baru di remote),
    commit kita dibuang, tarik versi terbaru, lalu perubahan diterapkan ulang (tanpa konflik rebase)."""
    for attempt in range(1, 4):
        git("pull", "--rebase", "--autostash", "--quiet", "origin", "main")
        with open(STATUS, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("agents"), list):
            data["agents"] = []
        ts = now_wib()
        msg = mutate(data, ts)
        write_status(data, ts)
        git("add", "status.json")
        msg = msg if len(msg) <= 100 else msg[:99] + "…"
        git("commit", "--quiet", "-m", msg)
        if no_push:
            print(f"OK (lokal, tanpa push): {msg}")
            return
        r = git("push", "--quiet", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"OK {sha}: {msg}")
            return
        print(f"push gagal (percobaan {attempt}): {r.stderr.strip()}", file=sys.stderr)
        git("reset", "--quiet", "--keep", "HEAD~1")  # buang commit kita saja; file lain tidak disentuh
        time.sleep(2 * attempt)
    die("push ke GitHub gagal setelah 3 percobaan (tidak ada perubahan yang tersimpan).", 4)


def main():
    ap = argparse.ArgumentParser(description="Perbarui status agen Kantor Virtual Vertex8 dan push ke GitHub.")
    ap.add_argument("--agent", help='nama atau id agen, mis. "Mr. Wahyudi" (untuk --add-agent: id baru, mis. "designer")')
    ap.add_argument("--state", choices=list(STATE_MAP))
    ap.add_argument("--task")
    ap.add_argument("--next", dest="nxt", default=None, help='tugas "Berikutnya" (opsional)')
    ap.add_argument("--output", default=None, help=f"hasil/keluaran singkat terakhir (opsional, maks {OUTPUT_MAX} karakter)")
    ap.add_argument("--add-agent", action="store_true", help="daftarkan bot baru (butuh --agent <id> dan --name)")
    ap.add_argument("--remove-agent", action="store_true", help="hapus bot (butuh --agent <id|nama>)")
    ap.add_argument("--name", help="nama tampilan bot (untuk --add-agent)")
    ap.add_argument("--role", help=f'peran bot (untuk --add-agent, bawaan "{DEFAULT_ROLE}")')
    ap.add_argument("--no-push", action="store_true", help="hanya ubah + commit lokal (untuk uji)")
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

    if a.task is not None and not task:
        die("--task kosong", 2)
    if (a.state is None) != (task is None):
        die("--state dan --task harus dipakai bersama", 2)
    if out is not None:
        if not out:
            die("--output kosong", 2)
        if len(out) > OUTPUT_MAX:
            out = out[:OUTPUT_MAX - 1].rstrip() + "…"
    if a.remove_agent and (task or nxt or out or name or role):
        die("--remove-agent tidak bisa digabung dengan opsi lain", 2)
    if not a.add_agent and not a.remove_agent:
        if task is None and out is None:
            die("butuh --state + --task (atau --output saja)", 2)
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
    for label, val in (("task", task), ("next", nxt), ("output", out), ("name", name), ("role", role)):
        guard(label, val)

    # kunci agar beberapa bot tidak bentrok
    lockf = open(os.path.join(REPO, ".git", "update-status.lock"), "w")
    fcntl.flock(lockf, fcntl.LOCK_EX)

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
            if ag is None:
                if len(agents) >= MAX_AGENTS:
                    die(f"maksimal {MAX_AGENTS} agen", 2)
                ag = {"id": aid, "name": name, "role": role or DEFAULT_ROLE, "tasks": []}
                agents.append(ag)
                add_log(data, ts, name, "Info", f"Bergabung ke kantor sebagai {ag['role']}")
                msgs.append(f"agent: tambah {name} ({aid})")
            else:
                ag["name"] = name
                if role:
                    ag["role"] = role
                msgs.append(f"agent: perbarui {name} ({aid})")
        else:
            ag = find_agent(agents, a.agent)
            if ag is None:
                die(f"agen '{a.agent}' tidak ditemukan. Pilihan: " + ", ".join(x.get("name", "?") for x in agents), 2)

        if task is not None:
            status = apply_state(ag, a.state, task, nxt)
            add_log(data, ts, ag.get("name"), status, task)
            msgs.append(f"status: {ag.get('name')} {a.state} - {task}")
        if out is not None:
            ag["last_output"] = out
            ag["last_output_at"] = ts
            if task is None:
                msgs.append(f"status: {ag.get('name')} output")
        return " | ".join(reversed(msgs))

    run_update(mutate, a.no_push)


if __name__ == "__main__":
    main()
