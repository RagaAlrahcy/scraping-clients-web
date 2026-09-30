"""Wrapper tipis di atas gspread untuk operasi Google Sheets.

Fokus modul ini hanya Google Sheets (connect/read/append/update cell).
Tidak ada scraping, database, Selenium, atau Playwright di sini.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials

try:  # gspread >= 5.12 memakai APIError baru
    from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
except ImportError:  # pragma: no cover - versi lama
    from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound  # type: ignore

    APIError = Exception  # type: ignore


class SheetsError(Exception):
    """Error umum dari GoogleSheetsManager."""


class CredentialsNotFoundError(SheetsError):
    """credentials.json tidak ditemukan atau tidak valid."""


class SpreadsheetNotFoundError(SheetsError):
    """Spreadsheet tidak ditemukan / belum di-share ke Service Account."""


class HeaderMismatchError(SheetsError):
    """Header di worksheet tidak sesuai dengan yang diharapkan."""


class GoogleSheetsManager:
    """Mengelola koneksi dan operasi dasar pada satu spreadsheet + worksheet."""

    def __init__(
        self,
        credentials_file: Union[str, Path],
        spreadsheet_name: str,
        worksheet_name: str = "Sheet1",
        headers: Optional[Sequence[str]] = None,
        scopes: Optional[Sequence[str]] = None,
        create_worksheet_if_missing: bool = True,
    ) -> None:
        self.credentials_file = Path(credentials_file)
        self.spreadsheet_name = spreadsheet_name
        self.worksheet_name = worksheet_name
        self.headers: List[str] = list(headers) if headers else []
        self.scopes = list(scopes) if scopes else [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        self.create_worksheet_if_missing = create_worksheet_if_missing

        # Diisi setelah connect() berhasil.
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
        self.worksheet: Optional[gspread.Worksheet] = None
        self.service_account_email: Optional[str] = None

    # ------------------------------------------------------------------
    # Koneksi
    # ------------------------------------------------------------------
    def _load_credentials(self) -> Credentials:
        """Memuat Service Account credential dari file JSON."""
        if not self.credentials_file.exists():
            raise CredentialsNotFoundError(
                f"File credential tidak ditemukan: {self.credentials_file}\n"
                "Buat Service Account di Google Cloud Console lalu simpan key JSON "
                "sebagai credentials.json (lihat README.md)."
            )

        try:
            credentials = Credentials.from_service_account_file(
                str(self.credentials_file), scopes=self.scopes
            )
        except (ValueError, GoogleAuthError, TypeError) as exc:
            raise CredentialsNotFoundError(
                f"credentials.json tidak valid atau bukan key Service Account: {exc}"
            ) from exc

        # Simpan email SA untuk pesan troubleshooting (bukan rahasia).
        try:
            with open(self.credentials_file, "r", encoding="utf-8") as handle:
                self.service_account_email = json.load(handle).get("client_email")
        except (OSError, ValueError):
            self.service_account_email = None

        return credentials

    def connect(self) -> gspread.Worksheet:
        """Autentikasi, buka spreadsheet, dan ambil worksheet.

        Return: objek gspread.Worksheet yang siap dipakai.
        """
        credentials = self._load_credentials()

        try:
            self.client = gspread.authorize(credentials)
        except (GoogleAuthError, OSError) as exc:
            raise SheetsError(f"Gagal autentikasi ke Google API: {exc}") from exc

        try:
            self.spreadsheet = self.client.open(self.spreadsheet_name)
        except SpreadsheetNotFound as exc:
            hint = (
                "Pastikan nama spreadsheet benar dan spreadsheet sudah di-share "
                "ke Service Account"
            )
            if self.service_account_email:
                hint += f" ({self.service_account_email})"
            hint += " dengan akses Editor."
            raise SpreadsheetNotFoundError(
                f"Spreadsheet '{self.spreadsheet_name}' tidak ditemukan. {hint}"
            ) from exc
        except APIError as exc:  # Drive/Sheets API belum diaktifkan, quota, dsb.
            raise SheetsError(self._explain_api_error(exc)) from exc

        self.worksheet = self._open_first_worksheet()
        return self.worksheet

    def _open_first_worksheet(self) -> gspread.Worksheet:
        """Ambil worksheet pertama (atau berdasarkan nama bila ada)."""
        assert self.spreadsheet is not None  # untuk type checker

        if self.worksheet_name:
            try:
                return self.spreadsheet.worksheet(self.worksheet_name)
            except WorksheetNotFound:
                if not self.create_worksheet_if_missing:
                    raise SheetsError(
                        f"Worksheet '{self.worksheet_name}' tidak ada di spreadsheet "
                        f"'{self.spreadsheet_name}'."
                    )
                # Buat worksheet baru dengan jumlah baris/kolom wajar.
                return self.spreadsheet.add_worksheet(
                    title=self.worksheet_name,
                    rows=1000,
                    cols=max(len(self.headers), 10),
                )

        # Fallback: worksheet pertama pada spreadsheet.
        worksheets = self.spreadsheet.worksheets()
        if not worksheets:
            return self.spreadsheet.add_worksheet(
                title="Sheet1", rows=1000, cols=max(len(self.headers), 10)
            )
        return worksheets[0]

    def _require_worksheet(self) -> gspread.Worksheet:
        if self.worksheet is None:
            raise SheetsError("Belum terhubung. Panggil connect() terlebih dahulu.")
        return self.worksheet

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def get_headers(self) -> List[str]:
        """Ambil baris pertama worksheet sebagai daftar header."""
        sheet = self._require_worksheet()
        try:
            row = sheet.row_values(1)
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc
        return [str(cell).strip() for cell in row]

    def ensure_headers(self) -> bool:
        """Pastikan header ada dan sesuai.

        Return True jika header baru dibuat, False jika header sudah benar.
        """
        if not self.headers:
            raise SheetsError("Daftar header belum didefinisikan (self.headers kosong).")

        sheet = self._require_worksheet()
        current = self.get_headers()

        if not current:
            # Worksheet masih kosong -> tulis header di baris 1.
            sheet.update(
                values=[self.headers], range_name="A1", value_input_option="RAW"
            )
            return True

        if current[: len(self.headers)] != self.headers:
            raise HeaderMismatchError(
                "Header worksheet tidak sesuai.\n"
                f"  Diharapkan : {self.headers}\n"
                f"  Ditemukan  : {current}"
            )

        return False

    # ------------------------------------------------------------------
    # Anti-duplikat & util
    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        """True bila worksheet belum punya data (hanya header/kosong)."""
        try:
            return len(self.get_all_records()) == 0
        except SheetsError:
            return len(self.get_headers()) == 0

    def find_row_by_website(self, website: str) -> int:
        """Cari nomor baris (1-based) yang kolom Website-nya cocok.

        Return -1 bila tidak ditemukan. Pencocokan memakai normalisasi
        (tanpa skema, tanpa www, tanpa trailing slash) supaya
        'http://www.x.com/' dan 'https://x.com' dianggap sama.
        """
        key = self.website_key(website)
        if not key:
            return -1

        headers = self.get_headers() or self.headers
        if "Website" not in headers:
            raise SheetsError("Kolom 'Website' tidak ada di header worksheet.")

        website_column = headers.index("Website") + 1

        try:
            column_values = self._require_worksheet().col_values(website_column)
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc

        # Baris 0 = header, jadi nomor baris = index + 1.
        for index, value in enumerate(column_values):
            if index == 0:
                continue
            if self.website_key(str(value)) == key:
                return index + 1

        return -1

    def website_exists(self, website: str) -> bool:
        """True bila website sudah terdaftar di worksheet (anti-duplikat)."""
        return self.find_row_by_website(website) > 0

    @staticmethod
    def website_key(website: Any) -> str:
        """Normalisasi URL untuk perbandingan anti-duplikat."""
        text = str(website or "").strip().lower()
        if not text or text in ("-", "none", "null"):
            return ""

        # Buang protokol.
        for prefix in ("https://", "http://"):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break

        text = text.split("#")[0].rstrip("/")

        # Buang www.
        if text.startswith("www."):
            text = text[4:]

        return text

    @staticmethod
    def identity_key(name: Any, city: Any = "") -> str:
        """Normalisasi 'nama bisnis + kota' untuk anti-duplikat.

        Dipakai untuk bisnis tanpa website (Website = "-") yang tidak bisa
        dicocokkan lewat `website_key()`.
        """
        parts = []
        for value in (name, city):
            text = str(value or "").strip().lower()
            if text in ("-", "none", "null"):
                text = ""
            # Sisakan huruf/angka saja agar "Klinik Sehat, Jl." == "klinik sehat jl".
            text = re.sub(r"[^0-9a-z]+", " ", text).strip()
            text = re.sub(r"\s+", " ", text)
            parts.append(text)

        if not parts[0]:
            return ""
        return f"{parts[0]}|{parts[1]}"

    def find_row_by_identity(self, name: str, city: str = "") -> int:
        """Cari nomor baris (1-based) berdasarkan Nama Bisnis + Kota.

        Return -1 bila tidak ditemukan. Dipakai main.py agar bisnis tanpa
        website (Website = "-") tidak ditulis berulang di sheet.
        """
        key = self.identity_key(name, city)
        if not key:
            return -1

        headers = self.get_headers() or self.headers
        if "Nama Bisnis" not in headers:
            raise SheetsError("Kolom 'Nama Bisnis' tidak ada di header worksheet.")

        name_column = headers.index("Nama Bisnis") + 1
        city_column = headers.index("Kota") + 1 if "Kota" in headers else -1

        sheet = self._require_worksheet()
        try:
            name_values = sheet.col_values(name_column)
            city_values = sheet.col_values(city_column) if city_column > 0 else []
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc

        for index, value in enumerate(name_values):
            if index == 0:  # baris header
                continue
            city_value = city_values[index] if index < len(city_values) else ""
            if self.identity_key(value, city_value) == key:
                return index + 1

        return -1

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def get_all_records(self) -> List[Dict[str, Any]]:
        """Ambil seluruh baris data sebagai list of dict (key = header)."""
        sheet = self._require_worksheet()
        try:
            return sheet.get_all_records()
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc

    def append_row(self, data: Union[Dict[str, Any], Sequence[Any]]) -> int:
        """Tambahkan satu baris data.

        data boleh berupa dict (dipetakan sesuai header worksheet) atau list/tuple
        (urutan harus sama dengan header). Return nomor baris yang ditulis,
        atau -1 jika nomor baris tidak bisa dibaca dari response.
        """
        sheet = self._require_worksheet()
        values = self._to_row(data)

        try:
            result = sheet.append_row(values, value_input_option="RAW")
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc

        return self._parse_updated_range(result)

    def update_cell(self, row: int, column: int, value: Any) -> None:
        """Update satu sel. row/column memakai index 1-based (seperti di Sheets).

        Contoh: update_cell(2, 5, "Sudah dihubungi") -> sel E2.
        """
        if row < 1 or column < 1:
            raise ValueError(
                "Parameter row dan column memakai index 1-based (minimal 1)."
            )

        sheet = self._require_worksheet()
        try:
            sheet.update_cell(row, column, value)
        except APIError as exc:
            raise SheetsError(self._explain_api_error(exc)) from exc

    # ------------------------------------------------------------------
    # Helper internal
    # ------------------------------------------------------------------
    def _to_row(self, data: Union[Dict[str, Any], Sequence[Any]]) -> List[Any]:
        """Normalisasi input menjadi list sesuai urutan header."""
        if isinstance(data, dict):
            headers = self.get_headers() or self.headers
            if not headers:
                raise SheetsError(
                    "Header belum ada, tidak bisa memetakan dict ke kolom."
                )
            return [data.get(header, "") for header in headers]

        if isinstance(data, (list, tuple)):
            return list(data)

        raise TypeError("append_row() hanya menerima dict, list, atau tuple.")

    @staticmethod
    def _parse_updated_range(result: Dict[str, Any]) -> int:
        """Ambil nomor baris dari response append_row()."""
        try:
            updated_range = result["updates"]["updatedRange"]  # 'Sheet1!A5:E5'
            cell_part = updated_range.split("!")[-1]
            row_part = cell_part.split(":")[0]
            return int("".join(ch for ch in row_part if ch.isdigit()))
        except (KeyError, IndexError, ValueError, TypeError):
            return -1

    def _explain_api_error(self, exc: Exception) -> str:
        """Terjemahkan error API Google menjadi pesan yang mudah dipahami."""
        text = str(exc)
        if "PERMISSION_DENIED" in text or "403" in text:
            hint = (
                "Akses ditolak. Pastikan spreadsheet sudah di-share ke Service Account"
            )
            if self.service_account_email:
                hint += f" {self.service_account_email}"
            hint += (
                " dengan role Editor, dan Google Sheets API + Google Drive API "
                "sudah diaktifkan."
            )
            return f"{hint}\nDetail: {text}"
        if "API has not been used" in text or "SERVICE_DISABLED" in text:
            return (
                "API belum diaktifkan di project Google Cloud. Aktifkan Google Sheets "
                f"API dan Google Drive API.\nDetail: {text}"
            )
        return f"Google API error: {text}"
