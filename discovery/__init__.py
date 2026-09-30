"""Tahap discovery: cari bisnis otomatis dari OpenStreetMap (tanpa API key).

Modul ini menyisipkan satu tahap sebelum pipeline lama:

    "klinik jakarta selatan"
       ├─ 1. parse_query()        -> kategori + nama daerah
       ├─ 2. Nominatim (OSM)      -> area/bbox + nama kota
       ├─ 3. Overpass API (OSM)   -> daftar bisnis + nama/alamat/telepon/website
       ├─ 4. WebsiteScraper       -> lengkapi email dari website bisnis
       └─ 5. GoogleSheetsManager  -> INSERT + anti-duplikat

Data berasal dari OpenStreetMap (ODbL) - gratis, tanpa API key, tanpa billing.

Catatan etika: hanya 1 request Nominatim + 1 request Overpass per pencarian,
memakai User-Agent dari config.USER_AGENT, dan memberi jeda DISCOVERY_DELAY.
"""

from .categories import (
    KEYWORD_MAP,
    CategoryMatch,
    available_keywords,
    build_category,
    category_from_tags,
    detect_keyword,
    filter_matches_tags,
    name_filter,
    normalize_text,
    parse_query,
    strip_keyword,
    title_case_place,
)
from .osm_discovery import (
    DEFAULT_NOMINATIM_URL,
    DEFAULT_OVERPASS_URLS,
    BusinessCandidate,
    BusinessDiscovery,
    DiscoveryError,
    DiscoveryResult,
    Location,
)

__all__ = [
    "BusinessDiscovery",
    "BusinessCandidate",
    "DiscoveryResult",
    "DiscoveryError",
    "Location",
    "CategoryMatch",
    "KEYWORD_MAP",
    "available_keywords",
    "build_category",
    "detect_keyword",
    "filter_matches_tags",
    "category_from_tags",
    "name_filter",
    "normalize_text",
    "parse_query",
    "strip_keyword",
    "title_case_place",
    "DEFAULT_NOMINATIM_URL",
    "DEFAULT_OVERPASS_URLS",
]
