import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reconstruction import build_features, masked, submission
from satellite import indices, reflectance
from geo import validate_geometry
from analysis import build_analysis


def test_spectral_math():
    b = {
        k: np.array([v], dtype="float32")
        for k, v in {
            "blue": 0.1,
            "red": 0.2,
            "nir": 0.6,
            "nir08": 0.55,
            "rededge1": 0.3,
            "swir16": 0.25,
            "swir22": 0.2,
        }.items()
    }
    result = indices(b)
    assert result["ndvi"][0] == pytest.approx(0.5)
    assert result["ndmi"][0] == pytest.approx(0.35 / 0.85)
    assert result["ndre"][0] == pytest.approx(0.25 / 0.85)
    assert result["bsi"][0] == pytest.approx(-0.25 / 1.15)


def test_offset_applied_exactly_once():
    asset = {"raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
    assert reflectance(
        np.array([500.0]), asset, {"earthsearch:boa_offset_applied": True}
    )[0] == pytest.approx(0.05)
    assert reflectance(
        np.array([1500.0]), asset, {"earthsearch:boa_offset_applied": False}
    )[0] == pytest.approx(0.05)


def test_masked_features_do_not_leak():
    frame = pd.DataFrame(
        {
            "anon_polygon_id": ["P"] * 3,
            "date": ["2025-05-01", "2025-05-02", "2025-05-03"],
            "primary_ndvi": [0.2, 0.9, 0.4],
            "s2_ndvi": [0.2, 0.9, 0.4],
            "ndvi_zscore": [0, 1000, 0],
        }
    )
    mask = np.array([False, True, False])
    feats = build_features(masked(frame, mask))
    assert feats.loc[1, "primary_ndvi_linear"] == pytest.approx(0.3)
    frame.loc[1, ["primary_ndvi", "s2_ndvi", "ndvi_zscore"]] = [-0.5, 0.1, -999]
    pd.testing.assert_frame_equal(feats, build_features(masked(frame, mask)))


def test_submission_contract(tmp_path):
    frame = pd.DataFrame(
        {
            "anon_polygon_id": ["P"] * 3,
            "date": ["2025-05-01", "2025-05-02", "2025-05-03"],
            "primary_ndvi": [0.2, np.nan, 0.4],
            "is_synthetic_gap": [False, True, False],
        }
    )
    source = tmp_path / "in.csv"
    dest = tmp_path / "out.csv"
    frame.to_csv(source, index=False)
    result = submission(source, dest, model_path=tmp_path / "missing.joblib")
    out = pd.read_csv(dest)
    assert result["rows"] == 1
    assert list(out.columns) == ["anon_polygon_id", "date", "primary_ndvi_true"]
    assert out.primary_ndvi_true.iloc[0] == pytest.approx(0.3)


def test_no_data_is_not_normal():
    result = build_analysis([], [], [], "2025-05-01", "2025-05-05")
    assert result["summary"]["unresolved"] == 5
    assert result["summary"]["latestNdvi"] is None
    assert not result["anomalies"]
    assert all(x["status"] == "unknown" for x in result["series"])


def test_invalid_geometry():
    with pytest.raises(ValueError):
        validate_geometry(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
            }
        )
    with pytest.raises(ValueError):
        validate_geometry(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]]],
            }
        )
