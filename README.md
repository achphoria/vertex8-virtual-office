# Kantor Virtual Vertex8

Kantor virtual bergaya **neon cyberpunk** (v4) yang menampilkan status 9 agent Vertex8 di 9 meja divisi:
01 Builder (Mr. Wakidi), 02 Ops & Data (Mr. Wiyadi), 03 Marketing (Mr. Wahyudi), 04 Member Success (Mr. Widodo),
05 Performance (Mr. Winarto), 06 Finance (Mr. Wibowo), 07 Content & Creative (Mr. Wawan), 08 HR & People (Mr. Wisnu),
09 Engineering & Facility (Mr. Warsito).

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
- Latar: `assets/office-neon.webp` (cadangan `assets/office-neon.jpg`), 1600×897. Semua posisi (kursi, laptop,
  lorong, bar KOPI, layar besar) dipetakan dalam koordinat piksel gambar ini lalu diskalakan responsif.
- **Tanpa angka bisnis:** area dashboard di layar besar dan kolom harga menu KOPI sudah dihitamkan di file aset;
  di atasnya halaman menggambar panel **STATUS TIM** (agen aktif, tugas selesai hari ini dari log, jam update WIB,
  log langsung) dan titik neon di menu.
- Bot neon berjalan di lantai: **kerja** → duduk di kursi mejanya dan mengetik (layar menyala); **tidak ada tugas
  aktif** → ngopi di bar KOPI VERTEX8 / sofa dan sesekali jalan-jalan; tugas berisi *laporan/report/analisa* →
  sesekali berdiri di depan layar besar; tugas **baru selesai** → lompat + konfeti neon + gelembung "Selesai!".
- Meja: field `desk` (1–9) per agent. Agent tanpa `desk` mengisi meja kosong pertama. Meja tanpa agent tampil
  redup dengan label "Segera hadir".
- Klik bot / meja / kartunya → detail: tugas sekarang, berikutnya, rutin, hasil terakhir (`last_output`), dan riwayat.
- Tombol **Mode Rekam** / `?rekam=1` → tampilan vertikal 9:16 bersih (judul + jam WIB live), tombol **Musik**
  (lo-fi WebAudio, tanpa file), tombol hilang sendiri setelah 3 detik mouse diam.
  Di mode rekam kamera menyapu kantor perlahan (dan fokus ke bot yang merayakan), plus daftar 9 meja di bawahnya.

## Memperbarui status

```bash
python3 update-status.py --agent "Mr. Wahyudi" --state working --task "Riset tren konten" [--next "Draf caption"] [--output "Hasil singkat"]
python3 update-status.py --agent grok --output "Hasil singkat terakhir"          # hanya hasil terakhir
python3 update-status.py --agent grok --step "lagi query data"                    # langkah kecil, sering & murah
python3 update-status.py --agent grok --state working --task "..." --step "..."   # tugas baru + langkah pertama
python3 update-status.py --add-agent --agent designer --name "Mr. Wiryo" [--role "Desain"] [--desk 4] [--state working --task "..."]
python3 update-status.py --remove-agent --agent designer
```

`--state`: `working` | `scheduled` | `done`. Skrip membaca dokumen terbaru dari Supabase, menerapkan perubahan,
**menulisnya ke Supabase dulu** (lewat RPC `kv_set_state` yang dilindungi token penulis), lalu sebagai cadangan
melakukan `git pull --rebase`, menulis `status.json`, commit, dan push. Keluar 0 bila minimal satu tujuan berhasil
(peringatan dicetak bila salah satu gagal). `--output` maks 280 karakter. Peran bawaan agen baru: "Asisten AI".
`--desk N` (1–9, hanya bersama `--add-agent`) memilih meja; tanpa `--desk` agen baru mendapat meja kosong pertama.
Meja yang sudah dipakai agen lain ditolak. `--add-agent --desk N` pada agen yang sudah ada memindahkan mejanya.

`--step` (maks 120 karakter) hanya menulis ke Supabase (tanpa commit git), tampil sebagai `↳ ...` di gelembung,
kartu, dan detail agen pada tugas "Sekarang". Butuh agen yang sedang kerja; `--state` apa pun mengganti tugas
"Sekarang" sehingga langkah lama otomatis hilang, dan langkah yang tidak diperbarui 30 menit disembunyikan.
Opsi uji: `--no-push` (commit lokal saja, tanpa Supabase), `--no-supabase` (GitHub saja).

Token penulis Supabase dibaca dari `~/.config/vertex8-office/writer_token` (atau env `KV_WRITER_TOKEN`) dan
**tidak pernah** disimpan di repo ini. Kunci Supabase di `index.html`/skrip adalah kunci *publishable* (hanya baca).

> Situs ini publik — jangan tulis angka bisnis (omzet, jumlah member) atau data pribadi. Teks berisi "Rp",
> "<angka> member", atau nomor telepon ditolak oleh skrip.
