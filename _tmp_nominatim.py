"""Probe sementara: struktur respons Nominatim untuk beberapa bentuk query."""
import json

import requests

HEADERS = {"User-Agent": "ProspekClientBot/1.0 (probe)"}
URL = "https://nominatim.openstreetmap.org/search"

for query in ["jakarta selatan", "bandung", "klinik jakarta selatan", "surabaya"]:
    try:
        resp = requests.get(
            URL,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "namedetails": 1,
                "extratags": 0,
            },
            headers=HEADERS,
            timeout=30,
        )
        print(f"=== {query!r} -> HTTP {resp.status_code}")
        if resp.status_code == 200 and resp.json():
            item = resp.json()[0]
            print("osm_type/osm_id :", item.get("osm_type"), item.get("osm_id"))
            print("addresstype     :", item.get("addresstype"))
            print("type            :", item.get("type"))
            print("class           :", item.get("class"))
            print("name            :", item.get("name"))
            print("display_name    :", str(item.get("display_name"))[:120])
            print("boundingbox     :", item.get("boundingbox"))
            print("address         :", json.dumps(item.get("address"), ensure_ascii=False))
            names = item.get("namedetails") or {}
            print("namedetails keys:", sorted(names)[:6])
        else:
            print("body:", resp.text[:200])
    except Exception as exc:  # noqa: BLE001
        print(f"=== {query!r} -> ERROR {type(exc).__name__}: {str(exc)[:140]}")
