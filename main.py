"""Entry point Tahap 3: Discovery (OpenStreetMap) -> Scraper -> Google Sheets.

Alur:
1. Ubah kalimat pencarian (mis. "klinik jakarta selatan") menjadi daftar
   bisnis lewat OpenStreetMap: Nominatim (geocode) + Overpass API.
2. Lengkapi email lewat WebsiteScraper untuk bisnis yang punya website.
3. Connect ke Google Sheets dan pastikan header (8 kolom) sudah sesuai.
4. Untuk setiap bisnis:
   a. Cek anti-duplikat (website, atau nama+kota bila tanpa website).
   b. Belum ada -> INSERT, sudah ada -> SKIP.
   c. Tampilkan hasil di terminal.
5. Cetak ringkasan.

Satu bisnis gagal TIDAK menghentikan program; error dicatat lalu lanjut.

Jalankan:
    python main.py -q "klinik jakarta selatan"
    python main.py -q "klinik jakarta selatan" --limit 15 --dry-run
    python main.py --urls https://contoh.com https://contoh2.com
    python main.py --list-keywords
"""

import argparse
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

import config
from discovery import (
    BusinessCandidate,
    BusinessDiscovery,
    DiscoveryResult,
    available_keywords,
)
from scraper import WebsiteScraper
from sheets import (
    CredentialsNotFoundError,
    GoogleSheetsManager,
    HeaderMismatchError,
    SheetsError,
    SpreadsheetNotFoundError,
)

SEPARATOR = "-" * 72

# Status ringkasan per bisnis/URL.
STATUS_INSERTED = "INSERT"
STATUS_SKIPPED = "SKIP (duplikat)"
STATUS_FAILED = "GAGAL"
STATUS_DRY_RUN = "DRY-RUN"


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
    manager: Optional[GoogleSheetsManager],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Scrape satu URL lalu INSERT/SKIP di Google Sheets.

    Return dict ringkasan: {url, name, status, row, data, error}.
    Fungsi ini tidak melempar exception: semua error Google Sheets
    ditangkap dan dikembalikan sebagai status GAGAL.
    """
    summary: Dict[str, Any] = {
        "url": url,
        "name": url,
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

    # 2) Lengkapi kolom yang tidak diisi scraper agar tidak ada sel kosong.
    for column in ("Nama Bisnis", "Kategori", "Kota", "Website", "Email",
                   "Nomor Telepon", "Alamat"):
        if not str(row_data.get(column, "")).strip():
            row_data[column] = config.EMPTY_VALUE
    row_data["Status"] = config.STATUS_DEFAULT
    summary["name"] = row_data["Nama Bisnis"]

    if dry_run:
        summary["status"] = STATUS_DRY_RUN
        print("     Sheet  : DRY-RUN (tidak menulis ke Google Sheets)")
        return summary

    if manager is None:
        summary["error"] = "GoogleSheetsManager tidak tersedia (dry-run?)."
        print("     Sheet  : GAGAL -> manager tidak tersedia")
        return summary

    # 3) Anti-duplikat + insert
    try:
        existing_row = manager.find_row_by_website(result.url)
        if existing_row > 0:
            summary["status"] = STATUS_SKIPPED
            summary["row"] = existing_row
            print(f"     Sheet  : sudah ada di baris {existing_row} -> SKIP")
            return summary

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


def process_candidate(
    candidate: BusinessCandidate,
    manager: Optional[GoogleSheetsManager],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """INSERT/SKIP satu BusinessCandidate hasil discovery di Google Sheets.

    Anti-duplikat: bisnis yang punya website dicek lewat
    `find_row_by_website()`; bisnis tanpa website ("-") dicek lewat
    `find_row_by_identity()` (nama + kota) karena tidak ada kunci URL.

    Return dict ringkasan: {url, name, status, row, data, error}.
    Fungsi ini tidak melempar exception: semua error Google Sheets ditangkap
    dan dikembalikan sebagai status GAGAL.
    """
    row_data = candidate.as_row()
    summary: Dict[str, Any] = {
        "url": candidate.website if candidate.website not in ("", "-") else candidate.name,
        "name": candidate.name,
        "status": STATUS_FAILED,
        "row": -1,
        "data": row_data,
        "error": None,
    }

    # Kolom yang belum diisi diisi EMPTY_VALUE supaya tidak ada sel kosong.
    for column in ("Nama Bisnis", "Kategori", "Kota", "Website", "Email",
                   "Nomor Telepon", "Alamat"):
        if not str(row_data.get(column, "")).strip():
            row_data[column] = config.EMPTY_VALUE
    row_data["Status"] = config.STATUS_DEFAULT

    print(f"     Nama    : {row_data['Nama Bisnis']}")
    print(f"     Kategori: {row_data['Kategori']} | Kota: {row_data['Kota']}")
    print(f"     Website : {row_data['Website']}")
    print(f"     Email   : {row_data['Email']} | Telepon: {row_data['Nomor Telepon']}")
    print(f"     Alamat  : {row_data['Alamat']}")
    if str(candidate.status or "").strip() not in ("", "-"):
        print(f"     Catatan : {candidate.status}")

    if dry_run:
        summary["status"] = STATUS_DRY_RUN
        print("     Sheet   : DRY-RUN (tidak menulis ke Google Sheets)")
        return summary

    if manager is None:
        summary["error"] = "GoogleSheetsManager tidak tersedia (dry-run?)."
        print("     Sheet   : GAGAL -> manager tidak tersedia")
        return summary

    try:
        # 1) Anti-duplikat
        if row_data["Website"] != config.EMPTY_VALUE:
            existing_row = manager.find_row_by_website(row_data["Website"])
        else:
            existing_row = manager.find_row_by_identity(
                row_data["Nama Bisnis"], row_data["Kota"]
            )

        if existing_row > 0:
            summary["status"] = STATUS_SKIPPED
            summary["row"] = existing_row
            print(f"     Sheet   : sudah ada di baris {existing_row} -> SKIP")
            return summary

        # 2) Insert baris baru
        written_row = manager.append_row(row_data)
        summary["status"] = STATUS_INSERTED
        summary["row"] = written_row
        print(
            f"     Sheet   : INSERT baris {written_row if written_row > 0 else '?'} "
            f"(Status: {config.STATUS_DEFAULT})"
        )
    except SheetsError as exc:
        summary["error"] = f"Google Sheets error: {exc}"
        print(f"     Sheet   : GAGAL -> {exc}")
    except Exception as exc:  # noqa: BLE001 - jaga loop tetap berjalan
        summary["error"] = f"Error tidak terduga: {exc}"
        print(f"     Sheet   : GAGAL -> {exc}")

    return summary


def print_summary(summaries: List[Dict[str, Any]]) -> None:
    """Cetak tabel ringkasan hasil proses."""
    if not summaries:
        print("Tidak ada bisnis/URL untuk diproses.")
        return

    print(SEPARATOR)
    print("RINGKASAN")
    print(SEPARATOR)
    print(f"{'No':<4}{'NAMA / URL':<46}{'STATUS':<16}{'BARIS':<7}")
    print("-" * 72)
    for index, item in enumerate(summaries, start=1):
        label = str(item.get("name") or item.get("url") or "-")
        short_label = label if len(label) <= 43 else label[:40] + "..."
        row = item["row"] if item["row"] > 0 else "-"
        print(f"{index:<4}{short_label:<46}{item['status']:<16}{str(row):<7}")

    inserted = sum(1 for i in summaries if i["status"] == STATUS_INSERTED)
    skipped = sum(1 for i in summaries if i["status"] == STATUS_SKIPPED)
    failed = sum(1 for i in summaries if i["status"] == STATUS_FAILED)
    dry = sum(1 for i in summaries if i["status"] == STATUS_DRY_RUN)

    print("-" * 72)
    line = (
        f"Total: {len(summaries)} | INSERT: {inserted} | "
        f"SKIP: {skipped} | GAGAL: {failed}"
    )
    if dry:
        line += f" | DRY-RUN: {dry}"
    print(line)

    errors = [i for i in summaries if i["error"]]
    if errors:
        print("\nDetail error:")
        for item in errors:
            label = item.get("name") or item.get("url")
            print(f"  - {label}: {item['error']}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Baca argumen command line."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Discovery bisnis dari OpenStreetMap (Nominatim + Overpass) -> "
            "scrape website -> INSERT ke Google Sheets."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Contoh:\n"
            '  python main.py -q "klinik jakarta selatan"\n'
            '  python main.py -q "apotek bandung" --limit 15 --dry-run\n'
            "  python main.py --urls https://contoh.com https://contoh2.com\n"
            "  python main.py --list-keywords\n"
        ),
    )
    parser.add_argument(
        "-q",
        "--query",
        default=None,
        help=(
            "Kalimat pencarian, mis. 'klinik jakarta selatan'. "
            "Default: config.SCRAPE_QUERY."
        ),
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help=f"Jumlah maksimum bisnis (default: {config.DISCOVERY_LIMIT}).",
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        default=None,
        metavar="URL",
        help="Lewati discovery, langsung scrape URL ini (mode Tahap 2).",
    )
    parser.add_argument(
        "--keyword",
        default=None,
        help="Paksa kategori tertentu, mis. 'apotek' (mengabaikan deteksi otomatis).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Jalankan discovery + scraping tanpa menulis ke Google Sheets.",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Jangan scrape website bisnis untuk melengkapi email.",
    )
    parser.add_argument(
        "--include-no-website",
        action="store_true",
        default=config.INCLUDE_NO_WEBSITE,
        help=(
            "Paksa ikut sertakan bisnis tanpa website (Website diisi '-'). "
            f"Default: config.INCLUDE_NO_WEBSITE = {config.INCLUDE_NO_WEBSITE}."
        ),
    )
    parser.add_argument(
        "--list-keywords",
        action="store_true",
        help="Tampilkan daftar kata kunci kategori yang dikenali lalu keluar.",
    )
    return parser.parse_args(argv)


def run_urls(
    urls: Sequence[str],
    scraper: WebsiteScraper,
    manager: Optional[GoogleSheetsManager],
    dry_run: bool,
) -> List[Dict[str, Any]]:
    """Mode Tahap 2: scrape daftar URL manual lalu INSERT/SKIP."""
    summaries: List[Dict[str, Any]] = []
    total = len(urls)

    for index, url in enumerate(urls, start=1):
        print(SEPARATOR)
        print(f"[{index}/{total}] Memproses: {url}")
        try:
            summaries.append(process_url(url, scraper, manager, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001 - lapisan pengaman terakhir
            print(f"     Fatal error pada URL ini: {exc}")
            summaries.append(
                {
                    "url": url,
                    "name": url,
                    "status": STATUS_FAILED,
                    "row": -1,
                    "data": {},
                    "error": f"Fatal error: {exc}",
                }
            )

        # Delay sopan antar-request (kecuali URL terakhir).
        if index < total and config.REQUEST_DELAY > 0:
            time.sleep(config.REQUEST_DELAY)

    return summaries


def run_discovery(
    args: argparse.Namespace,
    scraper: WebsiteScraper,
    manager: Optional[GoogleSheetsManager],
) -> List[Dict[str, Any]]:
    """Mode Tahap 3: discovery OSM -> scraping -> INSERT/SKIP."""
    query = args.query or config.SCRAPE_QUERY
    limit = args.limit if args.limit is not None else config.DISCOVERY_LIMIT
    limit = max(int(limit), 1)

    print(f"Query       : {query}")
    print(f"Limit       : {limit}")
    print(f"Mode        : {'DRY-RUN' if args.dry_run else 'TULIS ke Google Sheets'}")
    print(SEPARATOR)

    discovery = BusinessDiscovery(
        timeout=config.DISCOVERY_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
        nominatim_url=config.NOMINATIM_URL,
        overpass_urls=config.OVERPASS_URLS,
        delay=config.DISCOVERY_DELAY,
        include_no_website=bool(args.include_no_website),
        user_agent=config.USER_AGENT,
    )

    print("[1/3] Discovery di OpenStreetMap...")
    result: DiscoveryResult = discovery.discover(
        query,
        limit=limit,
        keyword=args.keyword,
        enrich_emails=not args.no_enrich,
        scraper=scraper,
    )

    for message in result.errors:
        print(f"     [WARNING] {message}")

    if result.location is not None:
        print(f"     Daerah  : {result.location.city} ({result.location.label})")
    print(f"     Kategori: {result.category_label}")
    print(f"     Mirror  : {result.overpass_url or '-'}")
    print(
        f"     Ditemukan: {result.raw_count} elemen mentah | "
        f"{len(result.candidates)} kandidat siap | "
        f"{result.with_website} punya website | "
        f"{result.duplicates_removed} duplikat dibuang | "
        f"{result.skipped_without_name} tanpa nama"
    )

    if not result.candidates:
        print("\n[WARNING] Tidak ada bisnis yang bisa diproses.")
        if result.error:
            print(f"          Penyebab: {result.error}")
        return []

    print(SEPARATOR)
    print("[2/3] Menulis hasil ke Google Sheets...")
    summaries: List[Dict[str, Any]] = []
    total = len(result.candidates)

    for index, candidate in enumerate(result.candidates, start=1):
        print(SEPARATOR)
        print(f"[{index}/{total}] {candidate.name}")
        try:
            summaries.append(process_candidate(candidate, manager, dry_run=args.dry_run))
        except Exception as exc:  # noqa: BLE001 - lapisan pengaman terakhir
            print(f"     Fatal error pada bisnis ini: {exc}")
            summaries.append(
                {
                    "url": candidate.website,
                    "name": candidate.name,
                    "status": STATUS_FAILED,
                    "row": -1,
                    "data": candidate.as_row(),
                    "error": f"Fatal error: {exc}",
                }
            )

    print(SEPARATOR)
    print("[3/3] Selesai.")
    return summaries


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.list_keywords:
        print("Kata kunci kategori yang dikenali:")
        for keyword in available_keywords():
            print(f"  - {keyword}")
        return 0

    print(SEPARATOR)
    print("Discovery (OpenStreetMap) -> Python Scraper -> Google Sheets")
    print(SEPARATOR)
    print(f"Spreadsheet : {config.SPREADSHEET_NAME}")
    print(f"Worksheet   : {config.WORKSHEET_NAME}")
    print(f"Credential  : {config.CREDENTIALS_FILE}")

    # 1) Siapkan scraper (dipakai untuk melengkapi email bisnis).
    scraper = WebsiteScraper(
        timeout=config.REQUEST_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
    )

    # 2) Siapkan Google Sheets (dilewati saat --dry-run).
    manager: Optional[GoogleSheetsManager] = None
    if args.dry_run:
        print("Mode        : DRY-RUN (Google Sheets tidak dihubungi)")
        print(SEPARATOR)
    else:
        print(SEPARATOR)
        manager = build_manager()
        if not connect_and_prepare(manager):
            return 1
        print(SEPARATOR)

    # 3) Jalankan pipeline (satu bisnis gagal != berhenti semua).
    if args.urls:
        print(f"Jumlah URL  : {len(args.urls)} (mode manual)")
        print(SEPARATOR)
        summaries = run_urls(args.urls, scraper, manager, dry_run=args.dry_run)
    else:
        summaries = run_discovery(args, scraper, manager)

    # 4) Ringkasan
    print_summary(summaries)

    # 5) Total data di sheet
    if manager is not None:
        try:
            records = manager.get_all_records()
            print(f"\nTotal data di worksheet: {len(records)} baris")
        except SheetsError as exc:
            print(f"[WARNING] Tidak bisa membaca ulang data: {exc}")

    print(SEPARATOR)
    print("[SELESAI] Buka spreadsheet untuk memverifikasi hasilnya.")
    print(SEPARATOR)

    # Exit code 1 bila tidak ada hasil, atau bila SEMUA baris gagal.
    if not summaries:
        return 1
    return 1 if all(i["status"] == STATUS_FAILED for i in summaries) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDibatalkan oleh pengguna.")
        sys.exit(130)
