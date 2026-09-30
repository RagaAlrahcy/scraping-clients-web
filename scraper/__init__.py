"""Paket scraper sederhana (requests + BeautifulSoup)."""

from .scraper import (
    DEFAULT_EMPTY,
    InvalidUrlError,
    ScrapeResult,
    ScraperError,
    WebsiteScraper,
)

__all__ = [
    "WebsiteScraper",
    "ScrapeResult",
    "ScraperError",
    "InvalidUrlError",
    "DEFAULT_EMPTY",
]
