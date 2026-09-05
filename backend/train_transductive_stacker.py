"""OOF-стекинг целевого набора без чтения скрытых целевых строк."""

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from reconstruction import build_features, gap_mask, masked, validate_frame
from source_model import extended_features, predict_bundle


CONTEXT = [
    "doy",
    "year",
    "sin",
    "cos",
    "primary_ndvi_linear",
    "primary_ndvi_mean",
    "primary_ndvi_pchip",
    "primary_ndvi_left",
    "primary_ndvi_right",
    "primary_ndvi_dl",
    "primary_ndvi_dr",
    "primary_ndvi_l2",
    "primary_ndvi_r2",
    "primary_ndvi_l3",
    "primary_ndvi_r3",
    "s2_ndvi_linear",
    "s2_ndvi_pchip",
    "s2_ndvi_dl",
    "s2_ndvi_dr",
    "landsat_ndvi_linear",
    "landsat_ndvi_pchip",
    "landsat_ndvi_dl",
    "landsat_ndvi_dr",
    "modis_ndvi_linear",
    "modis_ndvi_pchip",
    "modis_ndvi_dl",
    "modis_ndvi_dr",
    "s2_ndvi_date_fraction",
    "landsat_ndvi_date_fraction",
    "modis_ndvi_date_fraction",
    "s2_ndvi_season_fraction",
    "landsat_ndvi_season_fraction",
    "modis_ndvi_season_fraction",
    "peer_mean",
    "peer_median",
    "peer_std",
    "peer_count",
    "peer_corr",
    "peer_best",
]


def predictions(artifact, frame):
    base = build_features(frame)
    features = extended_features(frame.reset_index(drop=True), base)
    general, experts = predict_bundle(artifact["bundle"], features)
    weight = artifact["expertWeight"]
    prediction = (1 - weight) * general + weight * experts
    result = features[[column for column in CONTEXT if column in features]].copy()
    result.insert(0, "expert_prediction", experts)
    result.insert(0, "general_prediction", general)
    result.insert(0, "base_prediction", prediction)
    result.insert(3, "model_disagreement", general - experts)
    result["field_code"] = (
        frame.anon_polygon_id.str.split("-").str[-1].astype(int).to_numpy()
    )
    return result, np.clip(prediction, -1, 1)


def model(seed, leaves=15):
    return LGBMRegressor(
        n_estimators=900,
        num_leaves=leaves,
        learning_rate=0.025,
        min_child_samples=45,
        reg_lambda=25,
        reg_alpha=1.0,
        colsample_bytree=0.85,
        subsample=0.9,
        subsample_freq=1,
        n_jobs=4,
        random_state=seed,
        verbosity=-1,
    )


def rmse(target, prediction):
    return float(np.sqrt(np.mean((target - prediction) ** 2)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--folds", type=int, default=6)
    args = parser.parse_args()
    frame = pd.read_csv(args.input)
    validate_frame(frame)
    hidden = gap_mask(frame)
    if frame.loc[hidden, "primary_ndvi"].notna().any():
        raise ValueError("Скрытые целевые значения не должны присутствовать.")
    artifact = joblib.load(args.base_model)
    if artifact.get("kind") != "source_experts_v1":
        raise ValueError("Нужна базовая модель экспертов источников.")
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    visible_ids = np.flatnonzero(frame.primary_ndvi.between(-1, 1).to_numpy() & ~hidden)
    shuffled = np.random.default_rng(20260906).permutation(visible_ids)
    partitions = np.array_split(shuffled, args.folds)
    records = []
    for fold, selected in enumerate(partitions):
        path = cache / f"oof_{fold}.joblib"
        if path.exists():
            record = joblib.load(path)
        else:
            evaluation = np.zeros(len(frame), dtype=bool)
            evaluation[selected] = True
            clean = masked(frame, hidden | evaluation)
            features, base = predictions(artifact, clean)
            record = {
                "features": features.loc[evaluation].reset_index(drop=True),
                "base": base[evaluation],
                "target": frame.loc[evaluation, "primary_ndvi"].to_numpy(float),
            }
            joblib.dump(record, path)
        records.append(record)
        print(
            "features",
            fold,
            len(record["target"]),
            "base_rmse",
            rmse(record["target"], record["base"]),
            flush=True,
        )
    oof = []
    for fold, test in enumerate(records):
        train_x = pd.concat(
            [
                record["features"]
                for index, record in enumerate(records)
                if index != fold
            ],
            ignore_index=True,
        )
        train_y = np.concatenate(
            [
                record["target"] - record["base"]
                for index, record in enumerate(records)
                if index != fold
            ]
        )
        regressor = model(9100 + fold)
        regressor.fit(train_x, train_y, categorical_feature=["field_code"])
        correction = regressor.predict(test["features"])
        # Безопасный вес поправки выбирается только по честным OOF-прогнозам.
        oof.append(
            {"target": test["target"], "base": test["base"], "correction": correction}
        )
    target = np.concatenate([record["target"] for record in oof])
    base = np.concatenate([record["base"] for record in oof])
    correction = np.concatenate([record["correction"] for record in oof])
    scores = {
        weight: rmse(target, np.clip(base + weight * correction, -1, 1))
        for weight in (0.0, 0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 1.0)
    }
    selected_weight = min(scores, key=scores.get)
    print(
        "oof",
        {"base": rmse(target, base), "weights": scores, "selected": selected_weight},
        flush=True,
    )
    all_x = pd.concat([record["features"] for record in records], ignore_index=True)
    all_y = np.concatenate([record["target"] - record["base"] for record in records])
    final_model = model(9200)
    final_model.fit(all_x, all_y, categorical_feature=["field_code"])
    clean = masked(frame, hidden)
    final_x, final_base = predictions(artifact, clean)
    final_prediction = np.clip(
        final_base + selected_weight * final_model.predict(final_x), -1, 1
    )
    result = frame.loc[hidden, ["anon_polygon_id", "date"]].copy()
    result["primary_ndvi_true"] = final_prediction[hidden]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, float_format="%.8f")
    joblib.dump(
        {
            "model": final_model,
            "weight": selected_weight,
            "oof": scores,
            "columns": list(all_x.columns),
        },
        output.with_suffix(".joblib"),
    )
    print("written", output, "rows", len(result), "weight", selected_weight, flush=True)


if __name__ == "__main__":
    main()
