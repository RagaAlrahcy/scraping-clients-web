"""Probe sementara: validasi sintaks query Overpass + ketersediaan mirror."""
import json

import requests

HEADERS = {"User-Agent": "ProspekClientBot/1.0 (probe)"}
LOG = "C:/Users/msi modern/OneDrive/Desktop/scraping-clients-web-main/_tmp_ovp.txt"


def log(line=""):
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(str(line) + "\n")


open(LOG, "w", encoding="utf-8").close()

AREA_QUERY = (
    "[out:json][timeout:60];"
    "area(3605802438)->.a;"
    '(nwr[amenity~"^(clinic|doctors)$"](area.a););'
    "out center tags 5;"
)

BBOX_QUERY = (
    "[out:json][timeout:60];"
    '(nwr[amenity~"^(clinic|doctors)$"](-6.3650,106.7374,-6.2026,106.8669););'
    "out center tags 5;"
)

NAME_QUERY = (
    "[out:json][timeout:60];"
    "area(3605802438)->.a;"
    '(nwr["name"~"toko bunga",i](area.a););'
    "out center tags 5;"
)

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

for label, query in (("AREA", AREA_QUERY), ("BBOX", BBOX_QUERY), ("NAME", NAME_QUERY)):
    for url in MIRRORS:
        log(f"--- {label} mencoba {url}")
        try:
            resp = requests.post(
                url, data={"data": query}, headers=HEADERS, timeout=70
            )
        except Exception as exc:  # noqa: BLE001
            log(f"    ERROR {type(exc).__name__}: {str(exc)[:100]}")
            continue

        if resp.status_code != 200:
            log(f"    HTTP {resp.status_code} body={resp.text[:80]!r}")
            continue

        try:
            payload = resp.json()
        except ValueError:
            log(f"    200 tapi bukan JSON: {resp.text[:80]!r}")
            continue

        elements = payload.get("elements", [])
        log(f"    OK HTTP 200 elements={len(elements)}")
        if elements:
            first = elements[0]
            log(f"    keys: {sorted(first)}")
            log(f"    tags: {json.dumps(first.get('tags'), ensure_ascii=False)[:240]}")
        break

log("PROBE SELESAI")

