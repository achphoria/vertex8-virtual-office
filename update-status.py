#!/usr/bin/env python3
"""Perbarui status agen di Kantor Virtual Vertex8 (status.json) lalu push ke GitHub.

Pakai:
  python3 /workspace/vertex8-virtual-office-repo/update-status.py \
      --agent "Vertex8 Marketing" --state working|scheduled|done --task "..." [--next "..."]

state:
  working   -> tugas "Sekarang" (Sedang kerja) diganti dengan --task
  scheduled -> agen tidak sedang kerja; --task jadi tugas "Berikutnya" (Terjadwal)
  done      -> tugas kerja dihapus; --task jadi "Baru selesai" (Selesai)
--next      -> (opsional) ganti tugas "Berikutnya" (Terjadwal)
Tugas berlabel lain (mis. "Rutin") tidak disentuh.

Keluar non-zero bila gagal (termasuk gagal push). JANGAN masukkan angka bisnis:
teks berisi "Rp", "<angka> member", atau nomor telepon akan ditolak.
"""
import argparse, datetime, fcntl, json, os, re, subprocess, sys, time

REPO = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(REPO, "status.json")
LOG_MAX = 20
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


def main():
    ap = argparse.ArgumentParser(description="Perbarui status agen Kantor Virtual Vertex8 dan push ke GitHub.")
    ap.add_argument("--agent", required=True, help='nama atau id agen, mis. "Vertex8 Marketing"')
    ap.add_argument("--state", required=True, choices=list(STATE_MAP))
    ap.add_argument("--task", required=True)
    ap.add_argument("--next", dest="nxt", default=None, help='tugas "Berikutnya" (opsional)')
    ap.add_argument("--no-push", action="store_true", help="hanya ubah + commit lokal (untuk uji)")
    a = ap.parse_args()

    task = a.task.strip()
    nxt = a.nxt.strip() if a.nxt else None
    if not task:
        die("--task kosong", 2)
    guard("task", task)
    guard("next", nxt)

    # kunci agar beberapa bot tidak bentrok
    lockf = open(os.path.join(REPO, ".git", "update-status.lock"), "w")
    fcntl.flock(lockf, fcntl.LOCK_EX)

    git("pull", "--rebase", "--autostash", "--quiet", "origin", "main")

    with open(STATUS, encoding="utf-8") as f:
        data = json.load(f)
    agents = data.get("agents") or []
    key = a.agent.strip().lower()
    ag = next((x for x in agents if str(x.get("name", "")).lower() == key or str(x.get("id", "")).lower() == key), None)
    if ag is None:
        die(f"agen '{a.agent}' tidak ditemukan. Pilihan: " + ", ".join(x.get("name", "?") for x in agents), 2)

    status, label = STATE_MAP[a.state]
    tasks = ag.get("tasks") or []
    work = [t for t in tasks if ststate(t.get("status")) == "work"]
    nexts = [t for t in tasks if ststate(t.get("status")) == "sched" and t.get("label", "Berikutnya") == "Berikutnya"]
    dones = [t for t in tasks if ststate(t.get("status")) == "done"]
    other = [t for t in tasks if t not in work and t not in nexts and t not in dones]  # mis. "Rutin"

    if a.state == "working":
        work = [{"status": status, "label": label, "text": task}]
    elif a.state == "scheduled":
        work = []
        nexts = [{"status": status, "label": label, "text": task}]
    else:  # done
        work = []
        dones = [{"status": status, "label": label, "text": task}]
    if nxt:
        if a.state == "scheduled":
            nexts.append({"status": "Terjadwal", "label": "Berikutnya", "text": nxt})
        else:
            nexts = [{"status": "Terjadwal", "label": "Berikutnya", "text": nxt}]
    ag["tasks"] = work + nexts + dones[:1] + other

    ts = now_wib()
    data.pop("updated", None)
    data["updated_at"] = ts
    log = data.get("log") if isinstance(data.get("log"), list) else []
    log.insert(0, {"t": ts, "agent": ag.get("name"), "status": status, "text": task})
    data["log"] = log[:LOG_MAX]

    # urutkan kunci supaya updated_at tetap dekat atas
    ordered = {"office": data.get("office", "Vertex8 HQ"), "updated_at": ts}
    ordered.update({k: v for k, v in data.items() if k not in ordered})
    with open(STATUS, "w", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")

    git("add", "status.json")
    msg = f"status: {ag.get('name')} {a.state} - {task}"[:72]
    git("commit", "--quiet", "-m", msg)
    if a.no_push:
        print(f"OK (lokal, tanpa push): {msg}")
        return

    for attempt in range(1, 4):
        r = git("push", "--quiet", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"OK {sha}: {msg}")
            return
        print(f"push gagal (percobaan {attempt}): {r.stderr.strip()}", file=sys.stderr)
        time.sleep(2 * attempt)
        git("pull", "--rebase", "--autostash", "--quiet", "origin", "main", check=False)
    die("push ke GitHub gagal setelah 3 percobaan (commit lokal tetap ada).", 4)


if __name__ == "__main__":
    main()
