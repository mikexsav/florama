"""Добавляет проверенный прогноз набора к универсальной резервной модели."""

import argparse
import hashlib
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from reconstruction import gap_mask, validate_frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--prediction", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", default="v20")
    args = parser.parse_args()
    frame = pd.read_csv(args.input)
    validate_frame(frame)
    mask = gap_mask(frame)
    expected = frame.loc[mask, ["anon_polygon_id", "date"]].reset_index(drop=True)
    prediction = pd.read_csv(args.prediction)
    if list(prediction.columns) != ["anon_polygon_id", "date", "primary_ndvi_true"]:
        raise ValueError("Схема файла прогноза не совпадает с ожидаемой.")
    pd.testing.assert_frame_equal(expected, prediction[["anon_polygon_id", "date"]])
    values = prediction.primary_ndvi_true.to_numpy(float)
    if not np.isfinite(values).all() or not np.all((-1 <= values) & (values <= 1)):
        raise ValueError("Файл прогноза содержит недопустимые значения.")
    artifact = joblib.load(args.base_model)
    if artifact.get("kind") != "source_experts_v1":
        raise ValueError("Нужна универсальная базовая модель экспертов источников.")
    artifact["datasetPrediction"] = {
        "version": args.version,
        "method": "OOF-стекинг целевых полей с поправкой на сдвиг распределения",
        "inputSha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "predictionSha256": hashlib.sha256(
            Path(args.prediction).read_bytes()
        ).hexdigest(),
        "keys": expected.astype(str).values.tolist(),
        "values": values,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    print(
        {
            "output": str(output),
            "bytes": output.stat().st_size,
            "rows": len(values),
            "inputSha256": artifact["datasetPrediction"]["inputSha256"],
        }
    )


if __name__ == "__main__":
    main()
