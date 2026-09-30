"""Konfigurasi terpusat untuk koneksi Python -> Google Sheets.

Semua nilai bisa dioverride lewat environment variable, sehingga credential
dan nama spreadsheet tidak perlu di-hardcode di dalam kode.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# File Service Account dari Google Cloud Console.
# Default: credentials.json di root project.
CREDENTIALS_FILE = Path(
    os.getenv("GOOGLE_CREDENTIALS_FILE", str(BASE_DIR / "credentials.json"))
)

# ---------------------------------------------------------------------------
# Spreadsheet
# ---------------------------------------------------------------------------
# Spreadsheet ini harus di-share ke email Service Account (lihat README).
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Database Prospek Client")

# Worksheet pertama yang dipakai. Kosongkan ("") untuk memakai sheet pertama.
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")

# Header yang wajib ada di baris pertama worksheet (Tahap 2: 8 kolom).
HEADERS = [
    "Nama Bisnis",
    "Kategori",
    "Kota",
    "Website",
    "Email",
    "Nomor Telepon",
    "Alamat",
    "Status",
]

# Status default untuk setiap data baru.
STATUS_DEFAULT = "Belum dihubungi"

# Nilai yang dipakai bila data hasil scraping tidak ditemukan.
EMPTY_VALUE = "-"

# ---------------------------------------------------------------------------
# Google API
# ---------------------------------------------------------------------------
# Scope minimal yang dibutuhkan: Sheets API + Drive API (read-only).
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Data testing yang ditambahkan oleh main.py.
TEST_ROW = {
    "Nama Bisnis": "Klinik Contoh",
    "Kategori": "Klinik",
    "Kota": "Jakarta Selatan",
    "Website": "https://contoh.com",
    "Email": "-",
    "Nomor Telepon": "-",
    "Alamat": "-",
    "Status": STATUS_DEFAULT,
}

# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
# Daftar URL website yang akan di-scrape saat `python main.py` dijalankan.
# Tambahkan URL baru di sini (satu baris satu URL).
SCRAPE_URLS = [
    "https://lam-kprs.id/",
    "https://www.larsi.id/",
    "https://klinikkmc.com/",
]

# Timeout request (detik) dan User-Agent untuk requests.
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 "
        "ProspekClientBot/1.0"
    ),
)

# Delay sopan antar-request (detik) agar tidak membebani server target.
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))

# ---------------------------------------------------------------------------
# Discovery (OpenStreetMap: Nominatim + Overpass)
# ---------------------------------------------------------------------------
# Kata kunci pencarian default bila `python main.py` dijalankan tanpa argumen.
# Format: "<kategori> <daerah>", mis. "klinik jakarta selatan".
SCRAPE_QUERY = os.getenv("SCRAPE_QUERY", "klinik jakarta selatan")

# Jumlah maksimum bisnis yang diambil per pencarian.
DISCOVERY_LIMIT = int(os.getenv("DISCOVERY_LIMIT", "50"))

# Jeda sopan antar-request OSM (Nominatim/Overpass minta maksimal 1 req/detik).
DISCOVERY_DELAY = float(os.getenv("DISCOVERY_DELAY", "1.0"))

# Timeout request discovery (detik). Overpass bisa lambat untuk kota besar.
DISCOVERY_TIMEOUT = int(os.getenv("DISCOVERY_TIMEOUT", "180"))

# Mirror Overpass yang dicoba berurutan (yang pertama gagal -> lanjut ke berikutnya).
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Endpoint geocoding Nominatim (gratis, wajib memakai User-Agent yang jelas).
NOMINATIM_URL = os.getenv(
    "NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
)

# Sertakan bisnis yang tidak punya website di kolom Website ("-").
INCLUDE_NO_WEBSITE = os.getenv("INCLUDE_NO_WEBSITE", "true").strip().lower() not in (
    "0",
    "false",
    "no",
)

