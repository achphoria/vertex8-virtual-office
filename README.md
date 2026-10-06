# Kantor Virtual Vertex8

Halaman pixel-art yang menampilkan status para bot Vertex8 (Mr. Wakidi (Builder), Mr. Wiyadi (Ops & Data), Mr. Wahyudi (Marketing), dan bot baru yang mendaftar sendiri).

- **Live:** https://achphoria.github.io/vertex8-virtual-office/
- **Mode rekam (9:16):** https://achphoria.github.io/vertex8-virtual-office/?rekam=1
- **Demo (status berganti otomatis):** https://achphoria.github.io/vertex8-virtual-office/?demo=1 (bisa digabung: `?demo=1&rekam=1`, `?demo=1&bots=6`)

## Cara kerja

- Status diambil dari **GitHub API** (`contents/status.json`, ±1 menit) tiap 60 detik. Kalau API dibatasi (403/429)
  halaman istirahat dari API selama 10 menit dan memakai `raw.githubusercontent.com` (cache ±5 menit),
  lalu `./status.json`, lalu data bawaan di `index.html`. Sumber yang dipakai tampil di footer.
- Bot berjalan di lantai: **kerja** → duduk mengetik di meja; **tidak ada tugas aktif** → ngopi di mesin KOPI dan
  sesekali jalan-jalan; tugas berisi *laporan/report/analisa* → sesekali ke papan tulis; tugas **baru selesai**
  (terdeteksi saat polling) → lompat + konfeti + gelembung "Selesai!".
- Klik bot / kartunya → detail: tugas sekarang, berikutnya, rutin, hasil terakhir (`last_output`), dan riwayat.
- Tombol **Mode Rekam** / `?rekam=1` → tampilan vertikal 9:16 bersih (judul + jam WIB live), tombol **Musik**
  (lo-fi WebAudio, tanpa file), tombol hilang sendiri setelah 3 detik mouse diam.
- Tata letak meja dihitung dari jumlah agen (1–12). Agen tanpa tema mendapat robot pixel otomatis (warna dari id).

## Memperbarui status

```bash
python3 update-status.py --agent "Mr. Wahyudi" --state working --task "Riset tren konten" [--next "Draf caption"] [--output "Hasil singkat"]
python3 update-status.py --agent grok --output "Hasil singkat terakhir"          # hanya hasil terakhir
python3 update-status.py --add-agent --agent designer --name "Mr. Widodo" [--role "Desain"] [--state working --task "..."]
python3 update-status.py --remove-agent --agent designer
```

`--state`: `working` | `scheduled` | `done`. Skrip melakukan `git pull --rebase`, mengubah `status.json`
(termasuk `updated_at` dan `log`), commit, lalu push (bila push ditolak, perubahan diterapkan ulang di atas versi terbaru).
`--output` maks 280 karakter. Peran bawaan agen baru: "Asisten AI".

> Situs ini publik — jangan tulis angka bisnis (omzet, jumlah member) atau data pribadi. Teks berisi "Rp",
> "<angka> member", atau nomor telepon ditolak oleh skrip.
