"""Обучает LightGBM на видимой истории целевых полей и формирует CSV прогноза."""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from reconstruction import build_features, gap_mask, masked, validate_frame
from source_model import baselines, extended_features
from train_field_adaptation import examples


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reference", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    reference = pd.read_csv(a.reference)
    frame = pd.read_csv(a.input)
    validate_frame(reference)
    validate_frame(frame)
    gaps = gap_mask(frame)
    clean = masked(frame, gaps)
    parts = []
    weights = []
    for data, seeds, weight in [
        (reference, [142, 243, 344, 445, 546, 647], 1.0),
        (clean, [771, 882, 993, 1104, 1215, 1326], 4.0),
    ]:
        for seed in seeds:
            part = examples(data, seed)
            parts.append(part)
            weights.append(np.full(len(part[1]), weight))
    x = pd.concat([v[0] for v in parts], ignore_index=True)
    y = np.concatenate([v[1] for v in parts])
    w = np.concatenate(weights)
    linear, _ = baselines(x)
    model = LGBMRegressor(
        n_estimators=1600,
        num_leaves=63,
        learning_rate=0.02,
        min_child_samples=30,
        reg_lambda=15,
        reg_alpha=0.3,
        colsample_bytree=0.85,
        subsample=0.9,
        subsample_freq=1,
        n_jobs=2,
        random_state=52,
        verbosity=-1,
    )
    model.fit(x, y - linear, sample_weight=w, categorical_feature=["field_code"])
    all_x = extended_features(clean, build_features(clean))
    all_x["field_code"] = (
        clean.anon_polygon_id.str.split("-").str[-1].astype(int).to_numpy()
    )
    all_linear, _ = baselines(all_x)
    prediction = np.clip(all_linear + model.predict(all_x), -1, 1)
    result = frame.loc[gaps, ["anon_polygon_id", "date"]].copy()
    result["primary_ndvi_true"] = prediction[gaps]
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(a.output, index=False)
    print(
        {
            "rows": len(result),
            "min": float(result.primary_ndvi_true.min()),
            "max": float(result.primary_ndvi_true.max()),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
