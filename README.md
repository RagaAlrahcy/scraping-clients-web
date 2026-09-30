# Website → Python Scraper → Google Sheets

Pipeline sederhana untuk mengumpulkan data prospek client:

```text
Website  ->  Python Scraper  ->  Google Sheets
             (requests +          (gspread +
              BeautifulSoup)       Service Account)
```

> **Tahap 2**: scraping + insert dengan anti-duplikat.
> Belum ada PostgreSQL, Selenium, atau Playwright.

Alur tiap URL:

1. Scrape data bisnis dari website (nama, email, telepon, alamat).
2. Cek apakah website sudah ada di sheet (**anti-duplikat**).
3. Belum ada → **INSERT** baris baru · Sudah ada → **SKIP**.
4. Satu website gagal **tidak** menghentikan proses URL berikutnya.

## Struktur Project

```text
google-sheets-prospek/
├── main.py                      # Entry point: scrape semua URL -> INSERT/SKIP
├── config.py                    # Konfigurasi (spreadsheet, header, SCRAPE_URLS)
├── scraper/
│   ├── __init__.py
│   └── scraper.py               # Kelas WebsiteScraper + ScrapeResult
├── sheets/
│   ├── __init__.py
│   └── sheets_manager.py        # Kelas GoogleSheetsManager
├── selfcheck_offline.py         # Self-check offline (44 pemeriksaan, tanpa internet)
├── credentials.json             # TIDAK di-commit (buat sendiri, lihat di bawah)
├── credentials.json.example     # Template saja (bukan credential asli)
├── requirements.txt
├── .gitignore
└── README.md
```

## Kolom di Google Sheets (8 kolom)

| # | Kolom | Diisi oleh |
| --- | --- | --- |
| A | `Nama Bisnis` | Scraper (`og:site_name` → JSON-LD → `<title>` → `<h1>` → domain) |
| B | `Kategori` | Manual (tahap ini diisi `-`) |
| C | `Kota` | Manual (tahap ini diisi `-`) |
| D | `Website` | URL hasil normalisasi (dipakai sebagai kunci anti-duplikat) |
| E | `Email` | Scraper (`mailto:` → teks halaman → meta) |
| F | `Nomor Telepon` | Scraper (`tel:` → itemprop → regex, dinormalisasi `+62 …`) |
| G | `Alamat` | Scraper (`<address>` → itemprop → JSON-LD → heuristik kata kunci) |
| H | `Status` | `Belum dihubungi` (otomatis) |

Field yang tidak ditemukan diisi `-` (lihat `config.EMPTY_VALUE`), jadi
**tidak ada sel kosong** di sheet.

## Fitur `GoogleSheetsManager`

| Fungsi | Keterangan |
| --- | --- |
| `connect()` | Autentikasi Service Account, buka spreadsheet, ambil worksheet |
| `get_all_records()` | Ambil semua baris data sebagai list of dict |
| `append_row(data)` | Tambah satu baris (dict atau list) |
| `update_cell(row, column, value)` | Update satu sel (index 1-based, seperti di Sheets) |
| `get_headers()` | Ambil header baris pertama |
| `ensure_headers()` | Buat header bila worksheet kosong, error bila header berbeda |
| `find_row_by_website(url)` | Nomor baris website terkait, `-1` bila belum ada *(anti-duplikat)* |
| `website_exists(url)` | `True`/`False` apakah website sudah terdaftar *(anti-duplikat)* |
| `is_empty()` | `True` bila worksheet belum punya baris data |

## Fitur `WebsiteScraper`

| Fungsi | Keterangan |
| --- | --- |
| `scrape(url)` | Ambil + parsing satu URL, return `ScrapeResult` |
| `normalize_url(url)` | Tambah `https://` bila perlu, buang fragment/trailing slash |
| `is_valid_url(url)` | Validasi skema + host |
| `site_key(url)` | Kunci pembanding antar-URL (tanpa skema/www) |

`scrape()` **tidak pernah** melempar exception jaringan ke pemanggil; semua
kegagalan dikembalikan sebagai `ScrapeResult(success=False, error=...)`.

## Cara Kerja Anti-Duplikat

Perbandingan memakai `GoogleSheetsManager.website_key()` yang menormalkan URL:
protokol (`http`/`https`), `www.`, trailing slash, dan fragment `#` diabaikan.
Jadi **semua** bentuk di bawah dianggap website yang sama:

```text
https://example.com
http://www.example.com/
https://example.com/#kontak
```

`main.py` memanggil `find_row_by_website()` sebelum insert. Jika ditemukan di
baris ke-N, URL tersebut di-`SKIP` dan data **tidak** ditulis ulang — aman
dijalankan berkali-kali (idempotent).

## Setup

### 1. Buat virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependency

```bash
pip install -r requirements.txt
```

### 3. Buat `credentials.json` di Google Cloud Console

1. Buka <https://console.cloud.google.com/> lalu buat/pilih project.
2. **APIs & Services → Library**, aktifkan:
   - **Google Sheets API**
   - **Google Drive API**
3. **APIs & Services → Credentials** (atau **IAM & Admin → Service Accounts**)
   → **Create credentials → Service account**. Beri nama, misal `sheets-bot`.
4. Buka Service Account itu → tab **Keys** → **Add key → Create new key** →
   pilih **JSON** → **Create**. File JSON akan otomatis terunduh.
5. Rename file hasil unduhan menjadi `credentials.json` dan letakkan di **root
   folder project** (sejajar dengan `main.py`).
6. Catat nilai `client_email` di file tersebut (contoh:
   `sheets-bot@project-id.iam.gserviceaccount.com`) — dibutuhkan di langkah 4.

> `credentials.json.example` hanyalah template. Jangan diisi dengan data
> karangan; autentikasi hanya berhasil dengan key asli dari Google.

### 4. Beri akses spreadsheet ke Service Account

1. Buat spreadsheet bernama **`Database Prospek Client`** di Google Drive.
2. Klik **Share / Bagikan**.
3. Paste `client_email` Service Account di atas, pilih role **Editor**
   (butuh Editor agar bisa append/update sel).
4. Simpan. Jika langkah ini dilewati, akan muncul error
   `SpreadsheetNotFound` walaupun nama spreadsheet sudah benar.

Worksheet akan diberi header otomatis oleh `main.py`:

```text
Nama Bisnis | Kategori | Kota | Website | Email | Nomor Telepon | Alamat | Status
```

> Jika baris 1 masih berisi header **Stage 1** (5 kolom), `main.py` akan
> melaporkan `Header worksheet tidak sesuai`. Perbaiki baris 1 agar sama persis
> dengan 8 kolom di atas, atau kosongkan worksheet agar dibuat otomatis.

### 5. Atur daftar URL yang akan di-scrape

Edit `config.py`, bagian `SCRAPE_URLS`:

```python
SCRAPE_URLS = [
    "https://example.com",
    "https://klinikcontoh.com",
    "https://bisnis-lain.id",
]
```

Satu baris satu URL. URL boleh ditulis tanpa `https://` (akan ditambahkan
otomatis). Jalankan lagi `python main.py` kapan saja untuk menambah URL baru —
website yang sudah ada di sheet akan di-`SKIP`, bukan diduplikasi.

### 6. Jalankan

```bash
python main.py
```

Output yang diharapkan:

```text
------------------------------------------------------------------------
Website -> Python Scraper -> Google Sheets
------------------------------------------------------------------------
Spreadsheet : Database Prospek Client
Worksheet   : Sheet1
Credential  : C:\...\google-sheets-prospek\credentials.json
Jumlah URL  : 1
------------------------------------------------------------------------
[OK] Terhubung ke Google Sheets.
     Service Account: sheets-bot@project-id.iam.gserviceaccount.com
     Header dibuat   : ['Nama Bisnis', 'Kategori', 'Kota', 'Website', ...]
------------------------------------------------------------------------
[1/1] Memproses: https://example.com
     URL    : https://example.com
     Nama Bisnis    : Example Domain
     Website        : https://example.com
     Email          : -
     Nomor Telepon  : -
     Alamat         : -
     Sheet  : INSERT baris 2 (Status: Belum dihubungi)
------------------------------------------------------------------------
RINGKASAN
------------------------------------------------------------------------
No  URL                                     STATUS          BARIS
------------------------------------------------------------------------
1   https://example.com                     INSERT          2
------------------------------------------------------------------------
Total: 1 URL | INSERT: 1 | SKIP: 0 | GAGAL: 0

Total data di worksheet: 1 baris
------------------------------------------------------------------------
[SELESAI] Buka spreadsheet untuk memverifikasi hasilnya.
------------------------------------------------------------------------
```

> Baris hasil `https://example.com` di atas **asli** dari pengetesan langsung
> ke internet. Website tersebut memang tidak memuat email/telepon/alamat apa
> pun, sehingga kolomnya diisi `-`. Website bisnis nyata biasanya
> mengembalikan data yang lebih lengkap.

Contoh isi sheet setelah dua URL diproses:

| Nama Bisnis | Kategori | Kota | Website | Email | Nomor Telepon | Alamat | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Klinik Sehat | - | - | https://kliniksehat.id | info@kliniksehat.id | +62 812 3456 7890 | Jl. Melati No. 10, Jakarta | Belum dihubungi |
| Example Domain | - | - | https://example.com | - | - | - | Belum dihubungi |

### 7. Jalankan ulang untuk menguji anti-duplikat

Jalankan `python main.py` lagi dengan `SCRAPE_URLS` yang sama:

```text
[1/1] Memproses: https://example.com
     URL    : https://example.com
     Nama Bisnis    : Example Domain
     ...
     Sheet  : sudah ada di baris 2 -> SKIP
------------------------------------------------------------------------
Total: 1 URL | INSERT: 0 | SKIP: 1 | GAGAL: 0
```

Tidak ada baris baru yang ditambahkan.

## Self-Check Offline

Untuk memverifikasi scraper + logika anti-duplikat **tanpa** internet dan
**tanpa** kredensial Google:

```bash
python selfcheck_offline.py
```

Script ini memakai HTML fixture dan stub `gspread`, lalu menjalankan **44
pemeriksaan** (parsing scraper, `ensure_headers`, `append_row`, anti-duplikat,
`SKIP` saat dijalankan ulang, dan toleransi error Google Sheets). Baris
terakhirnya:

```text
SELESAI: semua pemeriksaan lulus (offline, tanpa panggilan Google API).
```

Exit code `0` = semua lulus, `1` = ada pemeriksaan yang gagal.

## Menyesuaikan Scraper

Nilai yang bisa diubah lewat environment variable:

| Variable | Default | Keterangan |
| --- | --- | --- |
| `REQUEST_TIMEOUT` | `15` | Timeout request (detik) |
| `REQUEST_DELAY` | `1.0` | Jeda sopan antar-request (detik) |
| `USER_AGENT` | Chrome + `ProspekClientBot/1.0` | User-Agent request |

Contoh (PowerShell):

```powershell
$env:REQUEST_TIMEOUT = "30"
$env:REQUEST_DELAY = "2"
python main.py
```

Prioritas pengambilan setiap field ada di `scraper/scraper.py`, pada method
`extract_name()`, `extract_email()`, `extract_phone()`, dan
`extract_address()`. Tambahkan selector khusus untuk niche tertentu di method
tersebut bila perlu.

Email dari domain umum yang bukan milik bisnis (mis. `noreply@…`) dan alamat
bergambar (`info@…png`) otomatis disaring oleh blocklist di `scraper.py`.

> **Catatan etika**: hormati `robots.txt` dan Terms of Service website target,
> naikkan `REQUEST_DELAY` untuk batch besar agar server tidak terbebani, dan
> hanya ambil data yang memang dipublikasikan.

## Status Pengetesan

| Pengujian | Hasil |
| --- | --- |
| `python -m compileall` (semua modul) | ✅ Bersih, tanpa syntax error |
| `python selfcheck_offline.py` | ✅ **44/44 pemeriksaan lulus**, exit code 0 |
| Scraping langsung ke `https://example.com` | ✅ Berhasil, `<title>` → `Example Domain`, field kosong → `-` |
| Uji INSERT lalu jalankan ulang | ✅ Jalankan kedua menghasilkan `SKIP` (tidak ada duplikat) |
| Uji error Google Sheets (quota) | ✅ Program tidak berhenti, baris tidak ditambah, exit code 1 |
| Uji `SCRAPE_URLS` kosong | ✅ Pesan peringatan rapi, exit code 1 |
| Koneksi ke Google Sheets asli | ⏳ Perlu `credentials.json` dari Anda (lihat langkah 3–4) |

Semua pengujian di atas dijalankan pada virtual environment project
(Python 3.14.2) dengan `requests` + `beautifulsoup4` terpasang.

## Konfigurasi via Environment Variable

| Variable | Default | Keterangan |
| --- | --- | --- |
| `SPREADSHEET_NAME` | `Database Prospek Client` | Nama spreadsheet |
| `WORKSHEET_NAME` | `Sheet1` | Nama tab worksheet |
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` (root project) | Path file key Service Account |
| `REQUEST_TIMEOUT` | `15` | Timeout scraping (detik) |
| `REQUEST_DELAY` | `1.0` | Jeda antar-request (detik) |
| `USER_AGENT` | Chrome + `ProspekClientBot/1.0` | User-Agent request |

Contoh (PowerShell):

```powershell
$env:SPREADSHEET_NAME = "Spreadsheet Lain Saya"
$env:GOOGLE_CREDENTIALS_FILE = "D:\secrets\creds.json"
python main.py
```

## Keamanan

`.gitignore` sudah mengecualikan:

```text
credentials.json
.venv/
__pycache__/
*.pyc
.env
```

Script **tidak pernah** mencetak private key/token; hanya path file dan email
Service Account (aman dibagikan) untuk keperluan troubleshooting.

## Troubleshooting

| Error / Gejala | Penyebab | Solusi |
| --- | --- | --- |
| `File credential tidak ditemukan` | `credentials.json` belum ada / salah lokasi | Letakkan di root project (sejajar `main.py`), atau set `$env:GOOGLE_CREDENTIALS_FILE` |
| `credentials.json tidak valid atau bukan key Service Account` | File bukan JSON key Service Account (mis. key OAuth client) | Unduh ulang key bertipe *Service Account* dari Cloud Console |
| `SpreadsheetNotFound` | Nama spreadsheet beda, atau belum di-share ke Service Account | Cek nama **persis sama** (case-sensitive) lalu Share ke `client_email` dengan role **Editor** |
| `Akses ditolak` / `PERMISSION_DENIED` (403) | Role kurang, API belum aktif, atau key dari project berbeda | Ubah role jadi Editor; aktifkan Sheets API & Drive API di project yang sama dengan key |
| `API has not been used ... / SERVICE_DISABLED` | Google Sheets API / Drive API belum diaktifkan | APIs & Services → Library → Enable kedua API, tunggu 1–2 menit |
| `Header worksheet tidak sesuai` | Baris 1 bukan 8 kolom sesuai `config.HEADERS` | Perbaiki baris pertama agar sama persis (termasuk urutan), atau kosongkan worksheet agar dibuat otomatis |
| `Worksheet 'Sheet1' tidak ada` | Nama tab berbeda (mis. `Sheet 1`, `Data`) | Rename tab jadi `Sheet1`, atau set `$env:WORKSHEET_NAME = "Data"` |
| `insufficient authentication scopes` | Scope kurang saat membuat kredensial | Modul sudah memakai `spreadsheets` + `drive.readonly`; pastikan `config.SCOPES` tidak diubah |
| `ModuleNotFoundError: No module named 'gspread'` / `'bs4'` / `'requests'` | Virtual environment belum aktif / dependency belum diinstall | Aktifkan `.venv` lalu `pip install -r requirements.txt` |
| Aktivasi venv ditolak di PowerShell | Execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` lalu aktivasi ulang |
| Data tidak muncul di sheet | Melihat spreadsheet/tab yang berbeda | Pastikan spreadsheet bernama `Database Prospek Client` dan tab target sesuai; cek baris paling bawah |
| `429 / Quota exceeded` | Terlalu banyak request | Tunggu sebentar; untuk batch gunakan `get_all_records()` sekali lalu proses lokal |
| `Timeout setelah 15 detik` | Website lambat / memblokir bot | Naikkan `$env:REQUEST_TIMEOUT = "30"`; jika tetap gagal, website tersebut di-`SKIP` dan URL lain tetap diproses |
| `SSL certificate error` | Sertifikat website bermasalah/kedaluwarsa | URL akan ditandai `GAGAL` di ringkasan; perbaiki sertifikat target atau lewati domain tersebut |
| Scraper hanya menghasilkan `-` (data kosong) | Website memuat konten via JavaScript / pakai `robots.txt` | Scraper ini **tidak** menjalankan JavaScript. Untuk situs dinamis perlu Selenium/Playwright (tahap berikutnya) |
| Email salah / `info@…png` | Alamat email di dalam teks/gambar | Blocklist sudah menyaring pola umum; tambahkan domain/prefix ke `_EMAIL_BLOCKLIST_*` di `scraper.py` |
| Semua URL `GAGAL` (exit code 1) | Internet mati, DNS gagal, atau semua target memblokir | Cek koneksi; jalankan `python selfcheck_offline.py` dulu untuk memastikan kode scraper sehat |
| `505 - HTTP Version Not Supported` (via proxy) | Proxy/koneksi kantor memblokir request | Coba tanpa proxy atau dari jaringan lain |

## Catatan

- Modul ini hanya mengakses satu spreadsheet dan satu worksheet agar sederhana.
- Jika spreadsheet punya banyak tab, tentukan tab lewat `WORKSHEET_NAME`.
- `Kategori` dan `Kota` belum diisi otomatis pada tahap ini (diisi `-`) — bisa
  ditambahkan nanti lewat mapping domain atau klasifikasi otomatis.
- Dijalankan berulang kali aman (idempotent): website yang sudah ada di sheet
  akan di-`SKIP` berkat anti-duplikat.
- Tahap berikutnya (PostgreSQL / Selenium / Playwright untuk situs dinamis)
  belum disertakan; gunakan kembali `WebsiteScraper` dan
  `GoogleSheetsManager.append_row()`.
