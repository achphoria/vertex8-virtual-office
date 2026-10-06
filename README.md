# Kantor Virtual Vertex8

Halaman pixel-art yang menampilkan status para agent Vertex8 (Mr. Wakidi (Builder), Mr. Wiyadi (Ops & Data), Mr. Wahyudi (Marketing), dan bot baru yang mendaftar sendiri).

- **Live:** https://achphoria.github.io/vertex8-virtual-office/
- **Mode rekam (9:16):** https://achphoria.github.io/vertex8-virtual-office/?rekam=1
- **Demo (status berganti otomatis):** https://achphoria.github.io/vertex8-virtual-office/?demo=1 (bisa digabung: `?demo=1&rekam=1`, `?demo=1&bots=6`)

## Cara kerja

- Status utama ada di **Supabase** (tabel `kv_office_state`, satu baris JSON berbentuk sama dengan `status.json`).
  Halaman memuatnya lewat REST lalu berlangganan **Supabase Realtime** (websocket Phoenix mini, tanpa library),
  jadi perubahan muncul dalam **±1–2 detik**. Footer: *Sumber: Supabase Realtime (langsung)* + titik hijau.
  Saat realtime tersambung, halaman hanya cek ulang tiap 5 menit (jaga-jaga); bila terputus, sambung ulang otomatis
  (1s, 2s, 4s … maks 30s) dan cek Supabase tiap 60 detik.
- Bila Supabase tidak bisa diakses, halaman memakai cadangan: GitHub API (`contents/status.json`) →
  `raw.githubusercontent.com` → `./status.json` → data bawaan di `index.html`.
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
python3 update-status.py --agent grok --step "lagi query data"                    # langkah kecil, sering & murah
python3 update-status.py --agent grok --state working --task "..." --step "..."   # tugas baru + langkah pertama
python3 update-status.py --add-agent --agent designer --name "Mr. Widodo" [--role "Desain"] [--state working --task "..."]
python3 update-status.py --remove-agent --agent designer
```

`--state`: `working` | `scheduled` | `done`. Skrip membaca dokumen terbaru dari Supabase, menerapkan perubahan,
**menulisnya ke Supabase dulu** (lewat RPC `kv_set_state` yang dilindungi token penulis), lalu sebagai cadangan
melakukan `git pull --rebase`, menulis `status.json`, commit, dan push. Keluar 0 bila minimal satu tujuan berhasil
(peringatan dicetak bila salah satu gagal). `--output` maks 280 karakter. Peran bawaan agen baru: "Asisten AI".

`--step` (maks 120 karakter) hanya menulis ke Supabase (tanpa commit git), tampil sebagai `↳ ...` di gelembung,
kartu, dan detail agen pada tugas "Sekarang". Butuh agen yang sedang kerja; `--state` apa pun mengganti tugas
"Sekarang" sehingga langkah lama otomatis hilang, dan langkah yang tidak diperbarui 30 menit disembunyikan.
Opsi uji: `--no-push` (commit lokal saja, tanpa Supabase), `--no-supabase` (GitHub saja).

Token penulis Supabase dibaca dari `~/.config/vertex8-office/writer_token` (atau env `KV_WRITER_TOKEN`) dan
**tidak pernah** disimpan di repo ini. Kunci Supabase di `index.html`/skrip adalah kunci *publishable* (hanya baca).

> Situs ini publik — jangan tulis angka bisnis (omzet, jumlah member) atau data pribadi. Teks berisi "Rp",
> "<angka> member", atau nomor telepon ditolak oleh skrip.
