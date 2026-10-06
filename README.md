# Kantor Virtual Vertex8

Halaman pixel-art yang menampilkan status para bot Vertex8 (Grok Bot, Vertex8 Analyst, Vertex8 Marketing).

- **Live:** https://achphoria.github.io/vertex8-virtual-office/
- Halaman mengambil `status.json` dari `raw.githubusercontent.com` (cepat diperbarui), lalu `./status.json`, lalu data bawaan di `index.html`. Dicek ulang tiap 60 detik.

## Memperbarui status

```bash
python3 update-status.py --agent "Vertex8 Marketing" --state working --task "Riset tren konten" [--next "Draf caption"]
```

`--state`: `working` | `scheduled` | `done`. Skrip melakukan `git pull --rebase`, mengubah `status.json`
(termasuk `updated_at` dan `log`), commit, lalu push.

> Situs ini publik — jangan tulis angka bisnis (omzet, jumlah member) atau data pribadi.
