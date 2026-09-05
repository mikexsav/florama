import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DB_PATH", str(Path("artifacts/science-smoke.sqlite3").resolve()))
from store import migrate
from providers import scenes, weather, farmland
from satellite import analyze_scene

migrate()
geom = {
    "type": "Polygon",
    "coordinates": [
        [[39.70, 47.30], [39.71, 47.30], [39.71, 47.31], [39.70, 47.31], [39.70, 47.30]]
    ],
}
items, metadata = scenes(geom, "2026-07-01", "2026-08-31", 5)
print("catalog", metadata, flush=True)
best = min(items, key=lambda x: x["properties"].get("eo:cloud_cover", 100))
result = analyze_scene(best, geom, True)
Path("artifacts/live-scene.json").write_text(json.dumps(result), encoding="utf-8")
print("scene", {k: v for k, v in result.items() if k not in ["grid"]}, flush=True)
print("cells", len(result.get("grid", {}).get("features", [])), flush=True)
print("weather", weather(47.3, 39.7, "2026-07-01", "2026-07-05"), flush=True)
print("osm_fields", len(farmland([39.65, 47.35, 39.75, 47.45])["features"]), flush=True)
