"""Entry point Tahap 2: Website -> Python Scraper -> Google Sheets.

Alur:
1. Baca daftar URL dari config.SCRAPE_URLS.
2. Connect ke Google Sheets dan pastikan header (8 kolom) sudah sesuai.
3. Untuk setiap URL:
   a. Scrape data bisnis (requests + BeautifulSoup).
   b. Cek apakah website sudah ada di sheet (anti-duplikat).
   c. Belum ada -> INSERT, sudah ada -> SKIP.
   d. Tampilkan hasil di terminal.
4. Cetak ringkasan.

Satu website gagal TIDAK menghentikan program; error dicatat lalu lanjut.

Jalankan: python main.py
"""

import sys
import time
from typing import Any, Dict, List

import config
from scraper import WebsiteScraper
from sheets import (
    CredentialsNotFoundError,
    GoogleSheetsManager,
    HeaderMismatchError,
    SheetsError,
    SpreadsheetNotFoundError,
)

SEPARATOR = "-" * 72

# Status ringkasan per URL.
STATUS_INSERTED = "INSERT"
STATUS_SKIPPED = "SKIP (duplikat)"
STATUS_FAILED = "GAGAL"


def build_manager() -> GoogleSheetsManager:
    """Buat GoogleSheetsManager dari konfigurasi."""
    return GoogleSheetsManager(
        credentials_file=config.CREDENTIALS_FILE,
        spreadsheet_name=config.SPREADSHEET_NAME,
        worksheet_name=config.WORKSHEET_NAME,
        headers=config.HEADERS,
        scopes=config.SCOPES,
    )


def connect_and_prepare(manager: GoogleSheetsManager) -> bool:
    """Connect + pastikan header. Return True bila siap dipakai."""
    try:
        manager.connect()
    except CredentialsNotFoundError as exc:
        print("[ERROR] Kredensial bermasalah.")
        print(exc)
        print("\nLihat README.md bagian 'Cara membuat credentials.json'.")
        return False
    except SpreadsheetNotFoundError as exc:
        print("[ERROR] Spreadsheet tidak dapat dibuka.")
        print(exc)
        print(
            "\nTips: buka spreadsheet -> Share -> tambahkan email Service Account "
            "di atas sebagai Editor."
        )
        return False
    except SheetsError as exc:
        print("[ERROR] Gagal terhubung ke Google Sheets.")
        print(exc)
        return False

    print("[OK] Terhubung ke Google Sheets.")
    if manager.service_account_email:
        print(f"     Service Account: {manager.service_account_email}")

    try:
        existing = manager.get_headers()
        if existing:
            print(f"     Header saat ini : {existing}")
        created = manager.ensure_headers()
        if created:
            print(f"     Header dibuat   : {config.HEADERS}")
        else:
            print("     Header sudah sesuai.")
    except HeaderMismatchError as exc:
        print("[ERROR] Struktur header tidak cocok.")
        print(exc)
        print(
            "\nPerbaiki header di baris pertama worksheet agar sama persis "
            "(termasuk urutan), lalu jalankan ulang."
        )
        return False
    except SheetsError as exc:
        print("[ERROR] Gagal memeriksa/membuat header.")
        print(exc)
        return False

    return True


def print_result(result: Any) -> None:
    """Tampilkan hasil scraping di terminal."""
    if not result.success:
        print(f"     Hasil  : GAGAL -> {result.error}")
        return

    for key, value in result.data.items():
        print(f"     {key:<15}: {value}")


def process_url(
    url: str,
    scraper: WebsiteScraper,
    manager: GoogleSheetsManager,
) -> Dict[str, Any]:
    """Scrape satu URL lalu INSERT/SKIP di Google Sheets.

    Return dict ringkasan: {url, status, row, data, error}.
    Fungsi ini tidak melempar exception: semua error Google Sheets
    ditangkap dan dikembalikan sebagai status GAGAL.
    """
    summary: Dict[str, Any] = {
        "url": url,
        "status": STATUS_FAILED,
        "row": -1,
        "data": {},
        "error": None,
    }

    # 1) Scrape
    result = scraper.scrape(url)
    print(f"     URL    : {result.url}")
    print_result(result)

    if not result.success:
        summary["error"] = result.error
        return summary

    row_data = result.as_row()
    summary["data"] = row_data

    # 2) Anti-duplikat + insert
    try:
        existing_row = manager.find_row_by_website(result.url)
        if existing_row > 0:
            summary["status"] = STATUS_SKIPPED
            summary["row"] = existing_row
            print(f"     Sheet  : sudah ada di baris {existing_row} -> SKIP")
            return summary

        # 3) Insert data baru: lengkapi kolom yang tidak diisi scraper.
        #    Kategori & Kota belum ditentukan otomatis pada tahap ini,
        #    jadi diisi EMPTY_VALUE agar tidak ada sel kosong di sheet.
        for column in ("Nama Bisnis", "Kategori", "Kota", "Website", "Email",
                       "Nomor Telepon", "Alamat"):
            if not str(row_data.get(column, "")).strip():
                row_data[column] = config.EMPTY_VALUE
        row_data["Status"] = config.STATUS_DEFAULT
        written_row = manager.append_row(row_data)

        summary["status"] = STATUS_INSERTED
        summary["row"] = written_row
        print(
            f"     Sheet  : INSERT baris {written_row if written_row > 0 else '?'} "
            f"(Status: {config.STATUS_DEFAULT})"
        )
    except SheetsError as exc:
        summary["error"] = f"Google Sheets error: {exc}"
        print(f"     Sheet  : GAGAL -> {exc}")
    except Exception as exc:  # noqa: BLE001 - jaga loop tetap berjalan
        summary["error"] = f"Error tidak terduga: {exc}"
        print(f"     Sheet  : GAGAL -> {exc}")

    return summary


def print_summary(summaries: List[Dict[str, Any]]) -> None:
    """Cetak tabel ringkasan hasil proses."""
    if not summaries:
        print("Tidak ada URL untuk diproses.")
        return

    print(SEPARATOR)
    print("RINGKASAN")
    print(SEPARATOR)
    print(f"{'No':<4}{'URL':<40}{'STATUS':<16}{'BARIS':<7}")
    print("-" * 72)
    for index, item in enumerate(summaries, start=1):
        url = str(item["url"])
        short_url = url if len(url) <= 37 else url[:34] + "..."
        row = item["row"] if item["row"] > 0 else "-"
        print(f"{index:<4}{short_url:<40}{item['status']:<16}{str(row):<7}")

    inserted = sum(1 for i in summaries if i["status"] == STATUS_INSERTED)
    skipped = sum(1 for i in summaries if i["status"] == STATUS_SKIPPED)
    failed = sum(1 for i in summaries if i["status"] == STATUS_FAILED)

    print("-" * 72)
    print(
        f"Total: {len(summaries)} URL | INSERT: {inserted} | "
        f"SKIP: {skipped} | GAGAL: {failed}"
    )

    errors = [i for i in summaries if i["error"]]
    if errors:
        print("\nDetail error:")
        for item in errors:
            print(f"  - {item['url']}: {item['error']}")


def main() -> int:
    print(SEPARATOR)
    print("Website -> Python Scraper -> Google Sheets")
    print(SEPARATOR)
    print(f"Spreadsheet : {config.SPREADSHEET_NAME}")
    print(f"Worksheet   : {config.WORKSHEET_NAME}")
    print(f"Credential  : {config.CREDENTIALS_FILE}")
    print(f"Jumlah URL  : {len(config.SCRAPE_URLS)}")
    print(SEPARATOR)

    if not config.SCRAPE_URLS:
        print("[WARNING] config.SCRAPE_URLS masih kosong.")
        print("Tambahkan URL website di config.py lalu jalankan ulang.")
        return 1

    # 1) Siapkan Google Sheets
    manager = build_manager()
    if not connect_and_prepare(manager):
        return 1

    # 2) Siapkan scraper
    scraper = WebsiteScraper(
        timeout=config.REQUEST_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
    )

    # 3) Proses setiap URL (satu gagal != berhenti semua)
    summaries: List[Dict[str, Any]] = []
    total = len(config.SCRAPE_URLS)

    for index, url in enumerate(config.SCRAPE_URLS, start=1):
        print(SEPARATOR)
        print(f"[{index}/{total}] Memproses: {url}")
        try:
            summaries.append(process_url(url, scraper, manager))
        except Exception as exc:  # noqa: BLE001 - lapisan pengaman terakhir
            print(f"     Fatal error pada URL ini: {exc}")
            summaries.append(
                {
                    "url": url,
                    "status": STATUS_FAILED,
                    "row": -1,
                    "data": {},
                    "error": f"Fatal error: {exc}",
                }
            )

        # Delay sopan antar-request (kecuali URL terakhir).
        if index < total and config.REQUEST_DELAY > 0:
            time.sleep(config.REQUEST_DELAY)

    # 4) Ringkasan
    print_summary(summaries)

    # 5) Total data di sheet
    try:
        records = manager.get_all_records()
        print(f"\nTotal data di worksheet: {len(records)} baris")
    except SheetsError as exc:
        print(f"[WARNING] Tidak bisa membaca ulang data: {exc}")

    print(SEPARATOR)
    print("[SELESAI] Buka spreadsheet untuk memverifikasi hasilnya.")
    print(SEPARATOR)

    # Exit code 1 hanya bila SEMUA URL gagal.
    return 1 if all(i["status"] == STATUS_FAILED for i in summaries) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDibatalkan oleh pengguna.")
        sys.exit(130)
