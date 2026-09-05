import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["DB_PATH"] = str(Path("artifacts/science-smoke.sqlite3").resolve())
from providers import scenes
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
import rasterio
import numpy as np

geom = {
    "type": "Polygon",
    "coordinates": [
        [[39.70, 47.30], [39.71, 47.30], [39.71, 47.31], [39.70, 47.31], [39.70, 47.30]]
    ],
}
items, _ = scenes(geom, "2026-07-01", "2026-08-31", 5)
item = min(items, key=lambda x: x["properties"].get("eo:cloud_cover", 100))
print(item["properties"], flush=True)
for k in ["red", "blue", "nir", "swir16", "scl"]:
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="15"):
        with rasterio.open(item["assets"][k]["href"]) as src:
            bounds = transform_bounds("EPSG:4326", src.crs, 39.70, 47.30, 39.71, 47.31)
            data = src.read(1, window=from_bounds(*bounds, src.transform))
            print(
                k,
                "scales",
                src.scales,
                "offsets",
                src.offsets,
                "pcts",
                np.percentile(data, [0, 10, 50, 90, 100]),
                "unique",
                np.unique(data, return_counts=True) if k == "scl" else "",
                flush=True,
            )
