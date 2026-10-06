# Kantor Virtual Vertex8

Kantor virtual **2 lantai** bergaya **neon cyberpunk** (v5) yang menampilkan status 9 agent Vertex8 di 9 meja divisi:
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
- Latar v5: `assets/office-v5.webp` (cadangan `assets/office-v5.jpg`), 1600×959, **2 lantai**. Lantai 2: meja
  01 Builder, 02 Ops & Data, 03 Marketing, lounge + sofa, ruang rapat, perpustakaan. Lantai 1: meja 04–09, bar kopi,
  pantry. Kursi, monitor, lorong per lantai, tangga, bar kopi, pantry, sofa, perpustakaan, dan pintu ruang rapat
  dipetakan manual dalam koordinat piksel gambar (graf jalan + Dijkstra, termasuk jalur tangga).
- **Tanpa angka bisnis:** layar palsu di gambar sudah dicat ulang; di atasnya halaman menggambar layar langsung:
  2F **STATUS TIM** (agen aktif n/9, selesai hari ini dari log, jam update WIB) + **PAPAN PROYEK** (judul tugas) +
  **KEHADIRAN** (kerja/santai/staf online); 1F **SOROTAN** (tugas terakhir selesai) + **LOG LANGSUNG**.
- **Karakter semi-3D (canvas, tanpa gambar):** chibi robot-humanoid dengan gradasi volumetrik, rim light warna neon
  divisi, bayangan AO, tampak 3/4 / samping / belakang. Animasi: napas, kedip, tengok, jalan (bob + jejak langkah),
  ngetik (cahaya monitor di wajah), mikir (hologram), rayakan (lompat + konfeti neon). Aksesori: Builder visor + sabuk
  alat, Ops & Data kacamata holo, Marketing pin megafon, Member Success headset, Performance sweatband + stopwatch,
  Finance dasi + koin, Content kamera + baret, HR lanyard ID, Engineering helm proyek. Urutan gambar memakai y-sort
  dengan meja & tanaman depan sebagai penghalang (karakter di belakang meja tertutup mejanya).
- Agen **kerja** → duduk di kursinya dan mengetik; **santai** → jalan ke bar kopi, pantry, sofa lantai 2,
  perpustakaan, ruang rapat, lounge (naik-turun tangga); **baru selesai** → lompat + konfeti + gelembung "Selesai!".
- Ambient: kedip neon, kilau lampu kota di jendela, uap kopi, sapuan cahaya di lantai, layar berpendar.
  `prefers-reduced-motion` dihormati (efek berat dimatikan).
- Kamera: desktop menampilkan seluruh kantor dan zoom halus ke percakapan; HP mengikuti avatar staf (atau tur
  otomatis antar lantai); mode rekam menyapu kedua lantai dan fokus ke perayaan / percakapan (hanya "…").
- Meja: field `desk` (1–9) per agent. Agent tanpa `desk` mengisi meja kosong pertama. Tidak ada lagi label nama
  di atas meja (adegan lebih bersih); label divisi yang tercetak di gambar (mis. "01 BUILDER") tetap. Nama agent
  muncul di **tooltip** saat kursor di atas agent/meja, di kartu detail, dan di gelembung.
- Klik agent / meja → menu mini **Ngobrol** / **Lihat detail** (detail: tugas sekarang, berikutnya, rutin, hasil
  terakhir, riwayat). Klik kartu di Papan Tugas → detail.
- **Papan Tugas sembunyi otomatis:** kantor memenuhi lebar layar (skala sesuai, potongan tepi maks ±14% supaya
  tidak ada bingkai hitam besar; sisa tepi diisi latar buram). Tab neon tipis di tepi kanan
  (**PAPAN TUGAS · n aktif**) membuka panel sebagai lapisan: arahkan kursor / klik (desktop) atau ketuk (HP).
  Panel menutup sendiri saat kursor keluar, setelah ±7 detik tanpa aktivitas, ketuk di luar, atau `Esc`.
  Tombol **pin** menahan panel tetap terbuka (diingat di `localStorage`, kunci `kv_panel_pin`; di layar lebar
  kantor bergeser memberi ruang). Pintasan keyboard **T** = buka/tutup. Strip LOG dan footer dibuat lebih tipis.
- **Jaring pengaman status basi:** bila agent masih berstatus *kerja* tetapi tidak ada update (status maupun
  `--step`) lebih dari **45 menit**, halaman menampilkannya sebagai **Santai** dengan catatan kecil
  "tidak ada update sejak HH.MM" (kartu, gelembung, detail, mode rekam); robotnya ikut santai dan tidak dihitung
  "aktif". Waktu update terakhir diambil dari `step_at` tugas dan entri log terbaru agent itu. Dievaluasi ulang
  tiap menit; **data di Supabase/`status.json` tidak diubah** — begitu agent mengirim status atau langkah baru,
  tampilan kembali "Sedang kerja". Tutup tugas dengan `--state done` / `scheduled` agar tidak tergantung ini.
- Tombol **Mode Rekam** / `?rekam=1` → tampilan vertikal 9:16 bersih (judul + jam WIB live), tombol **Musik**
  (lo-fi WebAudio, tanpa file), tombol hilang sendiri setelah 3 detik mouse diam, plus daftar 9 meja di bawahnya.

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

## Ngobrol dengan Agent ala The Sims (khusus staf)

Tombol **Masuk** (email + sandi, Supabase Auth). Setelah masuk, staf terdaftar muncul sebagai **avatar manusia**
(warna dari nama, label nama + lencana **STAF**) di dekat tangga/pintu masuk lantai 1. Klik agent atau mejanya →
**Ngobrol** → avatar berjalan ke meja agent (pathfinding termasuk tangga), agent menoleh, lalu dock obrolan muncul
di bawah: kolom pesan + **Kirim**, **Riwayat** (laci samping), **Selesai ngobrol** (avatar kembali ke lounge).
Pesan tampil sebagai gelembung di atas kepala; selama menunggu, agent memunculkan hologram "mikir" dan dock menulis
*sedang membaca… / sedang mengetik…*; balasan muncul dengan efek mesin ketik (balasan panjang: **Baca selengkapnya**).
Saat ini hanya **Mr. Wawan — Content & Creative** yang bisa diajak ngobrol; agent lain menjawab
"Segera bisa diajak ngobrol". Tautan langsung: `#ngobrol`. Isi chat **tidak pernah** dimuat sebelum login dan
hanya bisa dibaca pemiliknya (RLS).

**Kehadiran (presence) untuk penonton lain:** tabel `kv_presence` (RLS) hanya berisi `pid` acak, nama tampilan
staf, keadaan (`hadir` / `ngobrol` + id agent), `waiting`, `talk_at`, `reply_at` — **tanpa** user_id, email, atau isi
chat. Publik hanya bisa membaca baris yang diperbarui ≤10 menit terakhir; tulis hanya lewat RPC
`kv_presence_set(p_state, p_agent, p_event)` / `kv_presence_leave()` (staf aktif saja, nama diambil dari
`kv_staff`). Halaman berlangganan perubahan lewat Realtime (plus cek tiap 60 dtk), detak tiap 60 dtk, keluar saat
logout / tutup tab; avatar basi (>3 menit) disembunyikan. Penonton lain hanya melihat gelembung **"…"**.
SQL: `supabase/kv_presence.sql`.

Alur: staf kirim pesan → baris `kv_chat_messages` (status `pending`) → trigger DB (pg_net) memanggil Edge Function
`kv-chat-notify` → fungsi itu POST ke **webhook routine** agent (bila secret sudah diset) → agent bangun di box dan
menjalankan `agent-chat.py` → balasan muncul langsung di browser lewat Realtime. Isi chat tidak dikirim ke webhook.

| Objek | Fungsi |
|---|---|
| `kv_staff` | allowlist staf: `email`, `display_name`, `allowed_agents[]`, `is_admin`, `active` (tanpa akses langsung dari web kecuali baris sendiri) |
| `kv_chat_agents` | daftar agent + `enabled` (publik, hanya nama) |
| `kv_chat_messages` | pesan; RLS: staf hanya baca utasnya sendiri & hanya insert pesan `staff` ke agent yang diizinkan; realtime aktif |
| `kv_chat_me()` | profil staf yang login (dipakai halaman) |
| `kv_presence` + `kv_presence_set / kv_presence_leave` | kehadiran avatar staf (publik: nama tampilan + keadaan saja) |
| `kv_chat_pending / kv_chat_reply / kv_chat_error` | RPC agent, dijaga **token penulis** |
| `kv_staff_admin` | RPC admin, dijaga **token admin** (`~/.config/vertex8-office/admin_token`, chmod 600) |
| Edge Function `kv-chat-notify` | membangunkan agent; debounce 60 dtk; tanpa secret → pesan tetap menunggu |

SQL lengkap: `supabase/kv_chat.sql`; kode fungsi: `supabase/functions/kv-chat-notify/index.ts`.

### Menambah staf (pemilik)

1. Supabase Dashboard → proyek *General Table* → **Authentication → Users → Add user → Create new user**: isi email +
   sandi sementara, centang **Auto Confirm User**. (Pendaftaran publik tidak dipakai; email tanpa allowlist tidak dapat apa-apa.)
2. Di box: `python3 staff-admin.py add --email nama@contoh.com --name "Nama Staf"` (bawaan agent: `content`;
   `--agents content,marketing`, `--admin` opsional).
3. Kirim email + sandi ke staf; staf klik **Masuk** di situs.

Lainnya: `staff-admin.py list | disable --email … | enable --email … | remove --email … | update --email … --agents …`
dan `staff-admin.py rotate-token`.

### Lupa password / atur password baru

- Di modal **Masuk** ada tautan **Lupa password?** → `POST /auth/v1/recover` dengan
  `redirect_to=https://achphoria.github.io/vertex8-virtual-office/`. URL itu **wajib** ada di Supabase →
  *Authentication → URL Configuration → Redirect URLs*; kalau tidak, Supabase memakai Site URL (`http://localhost:3000`).
  Menambah Redirect URL tidak mengubah Site URL / aplikasi lain.
- Saat halaman dibuka dari link email (`#access_token=…&type=recovery`, `?token_hash=…&type=recovery`, atau `?code=` PKCE),
  token langsung dihapus dari address bar (`history.replaceState`), lalu muncul modal **Atur Password Baru**
  (min. 8 karakter + konfirmasi) → `PUT /auth/v1/user`. Setelah berhasil, pengguna langsung masuk.
- Link lama yang terlanjur ke `http://localhost:3000/#access_token=…`: ganti awalan `http://localhost:3000/` dengan
  `https://achphoria.github.io/vertex8-virtual-office/` (bagian `#…` tetap). Link email sekali pakai dan berlaku 1 jam.

### Secret webhook (Dashboard → Edge Functions → Secrets)

`WEBHOOK_URL_CONTENT` (wajib), `WEBHOOK_KEY_CONTENT` (kunci pengirim), opsional `WEBHOOK_AUTH_HEADER`
(bawaan `Authorization`, nilai `Bearer <kunci>`; header lain → kunci mentah) dan `WEBHOOK_AUTH_PREFIX`.
Versi per agent: tambahkan `_<AGENT>` (mis. `WEBHOOK_AUTH_HEADER_CONTENT`). Agent lain: `WEBHOOK_URL_<ID>` + aktifkan
`enabled` di `kv_chat_agents`.

### Sisi agent

```bash
python3 agent-chat.py --agent content --pending                       # JSON: id, sender, content, history
python3 agent-chat.py --agent content --reply <id> --text "..."       # atau --text-file f.txt / --text - (stdin)
python3 agent-chat.py --agent content --error <id> --note "alasan"
```

`--reply` menandai pesan itu (dan pesan pending lebih lama di utas yang sama) *dibalas*. Status kantor otomatis:
langkah "Membalas chat staf" saat ada pesan, selesai bila tidak ada yang menunggu (`--no-status` untuk melewati).
Isi chat tidak pernah masuk ke status publik.
