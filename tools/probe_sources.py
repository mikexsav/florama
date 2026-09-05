import json
import requests

session = requests.Session()
session.headers["User-Agent"] = "Florama/1.0 (+https://crewloom.ru)"
base = "https://earth-search.aws.element84.com/v1"
query = {
    "collections": ["sentinel-2-l2a"],
    "bbox": [39.70, 47.30, 39.72, 47.32],
    "datetime": "2026-07-01T00:00:00Z/2026-08-31T23:59:59Z",
    "limit": 1,
}
try:
    r = session.post(base + "/search", json=query, timeout=30)
    print("STAC", r.status_code)
    f = r.json()["features"][0]
    print("scene", f["id"], f["properties"]["datetime"])
    print(
        json.dumps(
            {
                k: {x: v[x] for x in ("href", "raster:bands", "eo:bands") if x in v}
                for k, v in f["assets"].items()
                if k
                in [
                    "red",
                    "blue",
                    "green",
                    "nir",
                    "nir08",
                    "rededge1",
                    "swir16",
                    "swir22",
                    "scl",
                ]
            },
            indent=2,
        )
    )
except Exception as e:
    print("STAC_ERROR", type(e).__name__, str(e)[:160])
for name, url, params in [
    (
        "weather",
        "https://archive-api.open-meteo.com/v1/archive",
        {
            "latitude": 47.3,
            "longitude": 39.7,
            "start_date": "2026-07-01",
            "end_date": "2026-07-03",
            "daily": "temperature_2m_mean,precipitation_sum",
            "models": "era5_land",
            "timezone": "UTC",
        },
    ),
    (
        "cadastre",
        "https://nspd.gov.ru/api/geoportal/v2/search/geoportal",
        {"query": "61:44:0082014:7", "thematicSearchId": 1},
    ),
]:
    try:
        r = session.get(url, params=params, timeout=25)
        print(name, r.status_code, r.text[:1200])
    except Exception as e:
        print(name, type(e).__name__, str(e)[:160])
