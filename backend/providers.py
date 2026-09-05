"""Открытые источники. Сетевые ошибки не превращаются в выдуманные измерения."""

import hashlib
import json
import time
from datetime import date, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from store import transaction, dumps

STAC = "https://earth-search.aws.element84.com/v1"
USER_AGENT = "Florama/1.0 (+https://crewloom.ru; agricultural monitoring)"


def http():
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    # Каталог иногда обрывает TCP после успешного TLS. Повторяем отдельно
    # ошибки соединения/чтения и временные HTTP-ответы, не ретрая клиентские ошибки.
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.8,
        status_forcelist=[408, 425, 429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    session.mount(
        "https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    )
    return session


def fetch_json(url, params=None, body=None, ttl=3600):
    key = hashlib.sha256(dumps([url, params, body]).encode()).hexdigest()
    now = int(time.time())
    with transaction() as c:
        cached = c.execute(
            "SELECT value FROM cache WHERE key=? AND expires_at>?", (key, now)
        ).fetchone()
    if cached:
        return json.loads(cached["value"])
    last_error = None
    # Retry также на уровне запроса: некоторые обрывы происходят после ответа
    # прокси и не распознаются urllib3 как безопасно повторяемые.
    for attempt in range(3):
        try:
            with http() as s:
                response = (
                    s.post(url, json=body, timeout=(12, 60))
                    if body is not None
                    else s.get(url, params=params, timeout=(12, 60))
                )
                response.raise_for_status()
                value = response.json()
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    else:
        raise last_error
    with transaction() as c:
        c.execute("DELETE FROM cache WHERE expires_at<?", (now,))
        c.execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?)",
            (key, dumps(value), now + ttl),
        )
    return value


def geocode(query):
    value = fetch_json(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": 5, "accept-language": "ru"},
        ttl=86400,
    )
    return [
        {
            "name": v["display_name"],
            "lat": float(v["lat"]),
            "lon": float(v["lon"]),
            "bbox": [float(x) for x in v["boundingbox"]],
        }
        for v in value
    ]


def farmland(bounds):
    west, south, east, north = bounds
    if (
        not (-180 <= west < east <= 180 and -85 <= south < north <= 85)
        or east - west > 0.3
        or north - south > 0.3
    ):
        raise ValueError(
            "Приблизьте карту: область поиска не более 0,3° по каждой стороне."
        )
    query = f'[out:json][timeout:25];way["landuse"~"^(farmland|orchard|vineyard)$"]({south},{west},{north},{east});out tags geom 100;'
    # Два публичных Overpass-узла; лимит области не позволяет тяжёлый глобальный запрос.
    error = None
    for endpoint in [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]:
        try:
            data = fetch_json(endpoint, params={"data": query}, ttl=86400)
            features = []
            for item in data.get("elements", []):
                coords = [[x["lon"], x["lat"]] for x in item.get("geometry", [])]
                if len(coords) < 4 or coords[0] != coords[-1]:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "osmId": item["id"],
                            "name": item.get("tags", {}).get(
                                "name", f"Участок OSM {item['id']}"
                            ),
                            "source": "OpenStreetMap",
                            "landuse": item.get("tags", {}).get("landuse"),
                        },
                        "geometry": {"type": "Polygon", "coordinates": [coords]},
                    }
                )
            return {
                "type": "FeatureCollection",
                "features": features,
                "attribution": "© OpenStreetMap contributors, ODbL",
                "limit": 100,
            }
        except requests.RequestException as exc:
            error = exc
    raise RuntimeError(
        "Поиск OSM временно недоступен. Можно нарисовать контур самостоятельно."
    ) from error


def weather(lat, lon, start, end):
    fields = "temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
    archive_end = min(date.fromisoformat(end), date.today() - timedelta(days=6))
    rows = {}
    if date.fromisoformat(start) <= archive_end:
        data = fetch_json(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start,
                "end_date": str(archive_end),
                "daily": fields,
                "models": "era5",
                "timezone": "UTC",
            },
            ttl=86400,
        )
        daily = data.get("daily", {})
        for i, day in enumerate(daily.get("time", [])):
            rows[day] = {
                "date": day,
                **{k: daily[k][i] for k in fields.split(",") if k in daily},
                "source": "ERA5 / Open-Meteo",
                "timezone": "UTC",
            }
    if date.fromisoformat(end) > archive_end:
        data = fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": fields,
                "past_days": 7,
                "forecast_days": 1,
                "timezone": "UTC",
            },
            ttl=3600,
        )
        daily = data.get("daily", {})
        for i, day in enumerate(daily.get("time", [])):
            if start <= day <= end and day not in rows:
                rows[day] = {
                    "date": day,
                    **{k: daily[k][i] for k in fields.split(",") if k in daily},
                    "source": "Open-Meteo operational model",
                    "timezone": "UTC",
                }
    return sorted(rows.values(), key=lambda x: x["date"])


def scenes(geometry, start, end, limit=24):
    # Earth Search может очень долго строить intersects-ответы с page limit=100.
    # Берём компактную страницу по bbox; точное отсечение выполняет raster mask
    # конкретного Polygon/MultiPolygon в satellite.analyze_scene.
    from shapely.geometry import shape

    page_limit = max(10, min(24, limit + 6))
    data = fetch_json(
        STAC + "/search",
        body={
            "collections": ["sentinel-2-l2a"],
            "bbox": list(shape(geometry).bounds),
            "datetime": start + "T00:00:00Z/" + end + "T23:59:59Z",
            "limit": page_limit,
            "query": {"eo:cloud_cover": {"lt": 75}},
        },
        ttl=86400,
    )
    features = data.get("features", [])
    # Сначала выбираем наиболее безоблачный тайл на каждую дату.
    by_day = {}
    for f in features:
        day = f["properties"]["datetime"][:10]
        if day not in by_day or f["properties"].get("eo:cloud_cover", 100) < by_day[
            day
        ]["properties"].get("eo:cloud_cover", 100):
            by_day[day] = f
    chosen = sorted(by_day.values(), key=lambda x: x["properties"]["datetime"])
    count = len(chosen)
    if count > limit:
        import numpy as np

        chosen = [chosen[i] for i in np.linspace(0, count - 1, limit, dtype=int)]
    return chosen, {
        "catalogReturned": len(features),
        "uniqueDates": count,
        "selected": len(chosen),
        "pageLimit": page_limit,
        "spatialSearch": "bbox; exact mask on raster",
        "capped": count > limit
        or bool(
            data.get("links") and any(v.get("rel") == "next" for v in data["links"])
        ),
    }
