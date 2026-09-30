"""Discovery bisnis via OpenStreetMap: Nominatim (geocode) + Overpass API.

Alur:
    kalimat pencarian -> parse_query() -> geocode_place() -> Overpass
    -> BusinessCandidate -> siap dipetakan ke 8 kolom Google Sheets.

Modul ini memakai requests saja (tanpa Selenium/Playwright) dan tidak butuh
API key/billing. Semua kegagalan jaringan dikembalikan sebagai
DiscoveryResult(errors=[...]) - pola yang sama dengan WebsiteScraper.scrape().
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from scraper import WebsiteScraper

from .categories import (
    CategoryMatch,
    build_category,
    category_from_tags,
    detect_keyword,
    name_filter,
    normalize_text,
    strip_keyword,
    title_case_place,
)

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------
DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Mirror Overpass (fallback berurutan). Mirror publik bisa menolak request
# (HTTP 406/429), jadi rotasi + retry wajib ada.
DEFAULT_OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# Batas waktu (detik). Overpass kadang butuh >60 detik untuk area kota besar.
DISCOVERY_TIMEOUT = 180
NOMINATIM_TIMEOUT = 30
OVERPASS_TIMEOUT = 180

# Jeda sopan antar-request ke OSM (kebijakan penggunaan Nominatim/Overpass).
DISCOVERY_DELAY = 1.0

# Backoff sebelum mencoba mirror berikutnya.
RETRY_BACKOFF = (2.0, 5.0)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 ProspekClientBot/1.0"
)

# Status HTTP yang layak dicoba ulang di mirror lain.
_RETRYABLE_STATUS = (406, 408, 429, 500, 502, 503, 504)

_WHITESPACE_RE = re.compile(r"\s+")

# Tag OSM yang menandakan tempat sudah tutup/tidak aktif.
_INACTIVE_KEYS = ("disused", "abandoned", "razed", "demolished", "was")
_INACTIVE_VALUES = ("yes", "true", "1", "disused", "abandoned")


class DiscoveryError(Exception):
    """Error umum pada tahap discovery (geocode/Overpass)."""


# ---------------------------------------------------------------------------
# Struktur data
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Location:
    """Hasil geocode satu daerah dari Nominatim."""

    query: str
    display_name: str
    osm_type: str
    osm_id: int
    boundingbox: Tuple[float, float, float, float]  # (south, north, west, east)
    city: str
    addresstype: str = ""
    place_type: str = ""

    @property
    def area_id(self) -> Optional[int]:
        """ID area Overpass (3600000000 + osm_id) untuk relation administratif."""
        if self.osm_type == "relation" and self.osm_id > 0:
            return 3600000000 + self.osm_id
        return None

    @property
    def bbox(self) -> str:
        """Bounding box dalam format Overpass: south,west,north,east."""
        south, north, west, east = self.boundingbox
        return f"{south},{west},{north},{east}"

    @property
    def label(self) -> str:
        """Nama daerah yang enak dibaca (untuk terminal/log)."""
        return self.display_name or self.city or self.query


@dataclass
class BusinessCandidate:
    """Satu bisnis hasil discovery, siap dipetakan ke kolom Google Sheets."""

    name: str
    category: str = "-"
    city: str = "-"
    website: str = "-"
    email: str = "-"
    phone: str = "-"
    address: str = "-"
    status: str = "-"
    osm_type: str = ""
    osm_id: int = 0
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = "OpenStreetMap"

    @property
    def identity(self) -> str:
        """Kunci anti-duplikat untuk bisnis tanpa website."""
        return f"{normalize_text(self.name)}|{normalize_text(self.city)}"

    def as_row(self) -> Dict[str, str]:
        """Dict 8 kolom sesuai config.HEADERS."""
        return {
            "Nama Bisnis": self.name,
            "Kategori": self.category,
            "Kota": self.city,
            "Website": self.website,
            "Email": self.email,
            "Nomor Telepon": self.phone,
            "Alamat": self.address,
            "Status": self.status,
        }


@dataclass
class DiscoveryResult:
    """Hasil satu kali discovery (selalu dikembalikan, tidak melempar error)."""

    query: str
    candidates: List[BusinessCandidate] = field(default_factory=list)
    location: Optional[Location] = None
    category: Optional[CategoryMatch] = None
    errors: List[str] = field(default_factory=list)
    overpass_url: str = ""
    raw_count: int = 0
    skipped_without_name: int = 0
    duplicates_removed: int = 0

    @property
    def success(self) -> bool:
        """True bila tahap geocode + Overpass berhasil (walau 0 hasil)."""
        return not self.errors

    @property
    def error(self) -> Optional[str]:
        return self.errors[0] if self.errors else None

    @property
    def category_label(self) -> str:
        return self.category.category if self.category else "-"

    @property
    def place_label(self) -> str:
        if self.location is not None:
            return self.location.city or self.location.label
        return "-"

    @property
    def with_website(self) -> int:
        return sum(1 for item in self.candidates if item.website not in ("", "-"))


# ---------------------------------------------------------------------------
# BusinessDiscovery
# ---------------------------------------------------------------------------
class BusinessDiscovery:
    """Cari bisnis dari OpenStreetMap berdasarkan kata kunci + nama daerah.

    Pemakaian:
        discovery = BusinessDiscovery()
        result = discovery.discover("klinik jakarta selatan", limit=15)
        for candidate in result.candidates:
            print(candidate.name, candidate.website)

    Semua kegagalan jaringan dikembalikan sebagai DiscoveryResult(errors=[...]),
    tidak dilempar ke pemanggil - sama seperti WebsiteScraper.scrape().
    """

    def __init__(
        self,
        timeout: int = DISCOVERY_TIMEOUT,
        headers: Optional[Dict[str, str]] = None,
        nominatim_url: str = DEFAULT_NOMINATIM_URL,
        overpass_urls: Optional[Sequence[str]] = None,
        session: Optional[requests.Session] = None,
        delay: float = DISCOVERY_DELAY,
        include_no_website: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = int(timeout)
        self.nominatim_url = nominatim_url
        self.overpass_urls = [url for url in (overpass_urls or DEFAULT_OVERPASS_URLS) if url]
        self.delay = float(delay)
        self.include_no_website = bool(include_no_website)

        self.session = session if session is not None else requests.Session()
        base_headers = {"User-Agent": user_agent, "Accept": "application/json"}
        base_headers.update(headers or {})
        self.session.headers.update(base_headers)

        # Diisi setelah discover() berjalan (dipakai untuk log/testing).
        self.last_overpass_url = ""
        self.last_errors: List[str] = []

    # ------------------------------------------------------------------
    # Tahap 1: geocode nama daerah -> Location
    # ------------------------------------------------------------------
    def geocode_place(self, place: str) -> Optional[Location]:
        """Ubah nama daerah menjadi Location (bbox + area id).

        Return None bila daerah tidak ditemukan atau request gagal.
        """
        cleaned = _WHITESPACE_RE.sub(" ", str(place or "")).strip()
        if not cleaned:
            return None

        params = {
            "q": cleaned,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }

        try:
            response = self.session.get(
                self.nominatim_url, params=params, timeout=NOMINATIM_TIMEOUT
            )
        except requests.exceptions.RequestException as exc:
            self.last_errors.append(f"Nominatim gagal dihubungi: {self._short(exc)}")
            return None

        if response.status_code != 200:
            self.last_errors.append(
                f"Nominatim HTTP {response.status_code} untuk daerah '{cleaned}'."
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            self.last_errors.append("Respons Nominatim bukan JSON yang valid.")
            return None

        if not isinstance(payload, list) or not payload:
            self.last_errors.append(
                f"Daerah '{cleaned}' tidak ditemukan di OpenStreetMap."
            )
            return None

        location = self._location_from_payload(payload[0], cleaned)
        if location is None:
            self.last_errors.append(
                f"Daerah '{cleaned}' tidak punya bounding box yang bisa dipakai."
            )
        return location

    @staticmethod
    def _location_from_payload(item: Dict[str, Any], query: str) -> Optional[Location]:
        """Bangun Location dari satu objek hasil Nominatim."""
        try:
            south, north, west, east = (float(value) for value in (item.get("boundingbox") or [])[:4])
        except (TypeError, ValueError):
            return None

        address = item.get("address") or {}
        city = (
            address.get("city_district")
            or address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("county")
            or item.get("name")
            or query
        )

        try:
            osm_id = int(item.get("osm_id") or 0)
        except (TypeError, ValueError):
            osm_id = 0

        return Location(
            query=query,
            display_name=str(item.get("display_name") or ""),
            osm_type=str(item.get("osm_type") or ""),
            osm_id=osm_id,
            boundingbox=(south, north, west, east),
            city=title_case_place(str(city)),
            addresstype=str(item.get("addresstype") or ""),
            place_type=str(item.get("type") or ""),
        )

    # ------------------------------------------------------------------
    # Tahap 2: susun + kirim query Overpass
    # ------------------------------------------------------------------
    @staticmethod
    def build_overpass_query(
        filters: Iterable[str],
        location: Location,
        limit: int = 50,
        timeout: int = OVERPASS_TIMEOUT,
    ) -> str:
        """Susun QL Overpass dari filter + Location.

        Bila geocode berupa relation administratif, pencarian dibatasi dengan
        ``area(3600000000 + osm_id)->.a``; bila tidak, dipakai bounding box.
        ``out center tags`` mengambil tag lengkap tanpa geometri (respons ringan).

        Raise ValueError bila location kosong (query global terlalu berat).
        """
        if location is None:
            raise ValueError("Location wajib diisi untuk menyusun query Overpass.")

        valid = [str(item).strip() for item in filters if str(item or "").strip()]
        if not valid:
            raise ValueError("Minimal satu filter Overpass harus diberikan.")

        header = f"[out:json][timeout={int(timeout)}];"
        area_id = location.area_id
        if area_id is not None:
            header += f"area({area_id})->.a;"
            scope = "(area.a)"
        else:
            scope = f"({location.bbox})"

        statements = "".join(f"nwr{filter_text}{scope};" for filter_text in valid)
        return f"{header}({statements});out center tags {int(limit)};"

    def _overpass_request(self, query: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Kirim query ke mirror Overpass berurutan. Return (payload, url)."""
        last_error = ""

        for index, url in enumerate(self.overpass_urls):
            try:
                response = self.session.post(
                    url, data={"data": query}, timeout=self.timeout
                )
            except requests.exceptions.Timeout:
                last_error = f"timeout setelah {self.timeout} detik di {url}"
                self._backoff(index)
                continue
            except requests.exceptions.RequestException as exc:
                last_error = f"{url} -> {self._short(exc)}"
                self._backoff(index)
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = f"{url} -> HTTP {response.status_code} (dibatasi/ditolak)"
                self._backoff(index)
                continue

            if response.status_code != 200:
                last_error = f"{url} -> HTTP {response.status_code}"
                continue

            try:
                payload = response.json()
            except ValueError:
                last_error = f"{url} -> respons bukan JSON"
                self._backoff(index)
                continue

            if "elements" not in payload:
                remark = str(payload.get("remark") or "").strip()
                last_error = f"{url} -> respons tanpa 'elements' {remark}".strip()
                self._backoff(index)
                continue

            return payload, url

        if last_error:
            self.last_errors.append(f"Overpass gagal: {last_error}")
        return None, ""

    def _backoff(self, index: int) -> None:
        """Jeda sopan sebelum mencoba mirror berikutnya."""
        if index < len(RETRY_BACKOFF):
            time.sleep(RETRY_BACKOFF[index])

    # ------------------------------------------------------------------
    # Tahap 3: konversi elemen OSM -> BusinessCandidate
    # ------------------------------------------------------------------
    def to_candidates(
        self,
        elements: Iterable[Dict[str, Any]],
        location: Location,
        fallback_category: Optional[str] = None,
    ) -> Tuple[List[BusinessCandidate], int]:
        """Ubah elemen OSM menjadi kandidat bisnis.

        Return (kandidat, jumlah elemen yang dibuang karena tanpa nama).
        """
        candidates: List[BusinessCandidate] = []
        skipped = 0

        for element in elements:
            tags = element.get("tags") or {}
            if not isinstance(tags, dict) or not tags:
                continue

            name = self._clean(
                tags.get("name") or tags.get("name:id") or tags.get("operator")
            )
            if not name:
                skipped += 1
                continue

            if self._is_inactive(tags):
                continue

            website = self._first_url(
                tags.get("website"),
                tags.get("contact:website"),
                tags.get("url"),
            )
            email = self._first_email(tags.get("email"), tags.get("contact:email"))
            phone = self._clean(
                tags.get("phone")
                or tags.get("contact:phone")
                or tags.get("contact:mobile")
            )
            lat, lon = self._coordinates(element)

            candidates.append(
                BusinessCandidate(
                    name=name,
                    category=category_from_tags(tags) or fallback_category or "-",
                    city=location.city or "-",
                    website=website or "-",
                    email=email or "-",
                    phone=phone or "-",
                    address=self._build_address(tags) or "-",
                    status="-",
                    osm_type=str(element.get("type") or ""),
                    osm_id=int(element.get("id") or 0),
                    lat=lat,
                    lon=lon,
                )
            )

        return candidates, skipped

    @staticmethod
    def _clean(value: Any) -> str:
        """Rapikan nilai tag OSM (buang spasi/tanda pisah berlebih)."""
        if value is None:
            return ""
        text = _WHITESPACE_RE.sub(" ", str(value)).strip()
        return "" if text.lower() in ("", "nan", "none", "null") else text

    @staticmethod
    def _short(exc: BaseException) -> str:
        """Ringkas pesan exception agar log terminal tetap rapi."""
        message = str(exc).strip() or exc.__class__.__name__
        return _WHITESPACE_RE.sub(" ", message)[:160]

    @staticmethod
    def _first_url(*values: Any) -> str:
        """Ambil URL pertama yang masuk akal dari beberapa tag alternatif."""
        for value in values:
            text = BusinessDiscovery._clean(value)
            if not text:
                continue
            if text.startswith("//"):
                text = f"https:{text}"
            if not re.match(r"^https?://", text, re.IGNORECASE):
                host = text.split("/")[0]
                if "." not in host or " " in text:
                    continue
                text = f"https://{text.lstrip('/')}"
            return text.rstrip("/")
        return ""

    @staticmethod
    def _first_email(*values: Any) -> str:
        """Ambil email pertama yang valid (tag bisa berisi beberapa alamat)."""
        for value in values:
            text = BusinessDiscovery._clean(value)
            if not text:
                continue
            for chunk in re.split(r"[;,]", text):
                candidate = chunk.strip()
                if re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$", candidate):
                    return candidate.lower()
        return ""

    @staticmethod
    def _build_address(tags: Dict[str, Any]) -> str:
        """Susun alamat dari tag addr:* (fallback ke tag alamat bebas)."""
        street = " ".join(
            part
            for part in (
                BusinessDiscovery._clean(tags.get("addr:street")),
                BusinessDiscovery._clean(tags.get("addr:housenumber")),
            )
            if part
        )
        if not street:
            street = BusinessDiscovery._clean(tags.get("address"))

        parts = [
            street,
            BusinessDiscovery._clean(tags.get("addr:suburb") or tags.get("addr:hamlet")),
            BusinessDiscovery._clean(tags.get("addr:city") or tags.get("addr:town")),
            BusinessDiscovery._clean(tags.get("addr:postcode")),
        ]
        return ", ".join(part for part in parts if part)

    @staticmethod
    def _coordinates(element: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """Ambil koordinat dari node atau dari `center` (way/relation)."""
        for source in (element, element.get("center") or {}):
            lat = source.get("lat")
            lon = source.get("lon")
            if lat is None or lon is None:
                continue
            try:
                return float(lat), float(lon)
            except (TypeError, ValueError):
                continue
        return None, None

    @staticmethod
    def _is_inactive(tags: Dict[str, Any]) -> bool:
        """True bila tag menandakan tempat sudah tutup/tidak dipakai."""
        for key in _INACTIVE_KEYS:
            value = str(tags.get(key, "")).strip().lower()
            if value and (value in _INACTIVE_VALUES or value.startswith("disused")):
                return True

        lifecycle = str(tags.get("lifecycle") or "").strip().lower()
        return lifecycle in _INACTIVE_VALUES

    # ------------------------------------------------------------------
    # Tahap 4: anti-duplikat
    # ------------------------------------------------------------------
    @staticmethod
    def _dedup(candidates: Iterable[BusinessCandidate]) -> Tuple[List[BusinessCandidate], int]:
        """Buang duplikat (nama+kota sama, atau website sama).

        Return (kandidat_unik, jumlah_duplikat_dibuang). Kemunculan pertama
        dipertahankan karena urutan hasil Overpass tidak dijamin.
        """
        unique: List[BusinessCandidate] = []
        seen_identity: set = set()
        seen_website: set = set()
        removed = 0

        for candidate in candidates:
            identity = candidate.identity
            website = normalize_text(candidate.website)
            has_website = candidate.website not in ("", "-")

            if identity in seen_identity or (has_website and website in seen_website):
                removed += 1
                continue

            seen_identity.add(identity)
            if has_website:
                seen_website.add(website)
            unique.append(candidate)

        return unique, removed

    # ------------------------------------------------------------------
    # Tahap 5: orkestrasi
    # ------------------------------------------------------------------
    def find_businesses(
        self,
        filters: Iterable[str],
        location: Location,
        limit: int = 50,
        fallback_category: Optional[str] = None,
    ) -> Tuple[List[BusinessCandidate], int, int, str]:
        """Jalankan Overpass untuk Location yang sudah di-geocode.

        Return (kandidat, jumlah_mentah, jumlah_tanpa_nama, url_mirror).
        """
        try:
            query = self.build_overpass_query(filters, location, limit=limit)
        except ValueError as exc:
            self.last_errors.append(str(exc))
            return [], 0, 0, ""

        payload, url = self._overpass_request(query)
        if payload is None:
            return [], 0, 0, ""

        elements = payload.get("elements") or []
        candidates, skipped = self.to_candidates(
            elements, location, fallback_category=fallback_category
        )
        return candidates, len(elements), skipped, url

    def discover(
        self,
        query_text: str,
        limit: int = 50,
        keyword: Optional[str] = None,
        enrich_emails: bool = True,
        scraper: Optional[WebsiteScraper] = None,
    ) -> DiscoveryResult:
        """Cari bisnis dari kalimat pencarian bebas.

        Args:
            query_text: mis. "klinik jakarta selatan".
            limit: jumlah maksimum baris yang dikembalikan.
            keyword: paksa kategori tertentu (mengabaikan deteksi otomatis).
            enrich_emails: lengkapi email via WebsiteScraper bila tag OSM kosong.
            scraper: instance WebsiteScraper yang dipakai ulang (opsional).

        Return DiscoveryResult - tidak pernah melempar exception jaringan.
        """
        self.last_errors = []
        self.last_overpass_url = ""

        raw_query = str(query_text or "").strip()
        if not raw_query:
            return DiscoveryResult(
                query=raw_query, errors=["Kata kunci pencarian kosong."]
            )

        # 1) Pisahkan kategori + nama daerah.
        if keyword:
            category = build_category(keyword)
            place = strip_keyword(raw_query, detect_keyword(raw_query) or category)
        else:
            category, place = parse_query(raw_query)

        # Kata kunci WAJIB dibuang sebelum geocode; kalau tidak, Nominatim
        # mengembalikan POI (mis. "klinik jakarta selatan" -> klinik, bukan kota).
        if not place:
            place = raw_query
        if category is None:
            category = build_category(place)

        result = DiscoveryResult(query=raw_query, category=category)

        # 2) Geocode daerah.
        location = self.geocode_place(place)
        if location is None:
            result.errors.extend(self.last_errors or ["Geocode daerah gagal."])
            return result
        result.location = location

        if self.delay > 0:
            time.sleep(self.delay)

        # 3) Ambil bisnis dari Overpass.
        bounded_limit = max(int(limit), 1)
        candidates, raw_count, skipped, url = self.find_businesses(
            category.filters,
            location,
            limit=bounded_limit,
            fallback_category=category.category,
        )
        self.last_overpass_url = url
        result.overpass_url = url
        result.raw_count = raw_count
        result.skipped_without_name = skipped

        if not url:
            result.errors.extend(
                self.last_errors or ["Overpass tidak mengembalikan data."]
            )
            return result

        # 4) Anti-duplikat lalu batasi jumlah.
        candidates, removed = self._dedup(candidates)
        result.duplicates_removed = removed
        candidates = candidates[:bounded_limit]

        # 5) Lengkapi email dari website (hanya yang belum punya email).
        if enrich_emails:
            self.enrich_emails(candidates, scraper=scraper)

        # 6) Buang bisnis tanpa website bila diminta.
        if not self.include_no_website:
            candidates = [
                item for item in candidates if item.website not in ("", "-")
            ]

        result.candidates = candidates
        return result

    def enrich_emails(
        self,
        candidates: Iterable[BusinessCandidate],
        scraper: Optional[WebsiteScraper] = None,
    ) -> int:
        """Lengkapi email kandidat dengan men-scrape website-nya.

        Return jumlah email yang ditemukan. Hanya kandidat tanpa email TAPI
        punya website yang diproses, dan hasil scraping tidak pernah menimpa
        kolom Kategori/Kota/Telepon dari OSM.
        """
        targets = [
            item
            for item in candidates
            if item.website not in ("", "-") and item.email in ("", "-")
        ]
        if not targets:
            return 0

        active = scraper if scraper is not None else WebsiteScraper()
        found = 0

        for index, candidate in enumerate(targets):
            try:
                scraped = active.scrape(candidate.website)
            except Exception as exc:  # noqa: BLE001 - lapisan pengaman terakhir
                candidate.status = f"Email gagal: {self._short(exc)}"
                continue

            if not scraped.success:
                candidate.status = f"Email gagal: {scraped.error or 'tidak diketahui'}"
            else:
                email = self._clean(scraped.data.get("Email"))
                if email and email != "-":
                    candidate.email = email
                    found += 1

            if self.delay > 0 and index < len(targets) - 1:
                time.sleep(self.delay)

        return found






