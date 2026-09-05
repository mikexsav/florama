"""Пересчитывает загруженный CSV отдельной задачей с версией модели и хешами."""

import argparse
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path
import numpy as np
import pandas as pd
from reconstruction import submission, gap_mask
from store import transaction, dumps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-job", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--version", default="v15")
    args = parser.parse_args()
    with transaction() as conn:
        source = conn.execute(
            "SELECT * FROM jobs WHERE id=? AND kind='batch'", (args.source_job,)
        ).fetchone()
    if source is None:
        raise ValueError("Source job not found")
    source_path = Path(json.loads(source["payload"])["input"])
    frame = pd.read_csv(source_path)
    expected = frame.loc[gap_mask(frame), ["anon_polygon_id", "date"]].reset_index(
        drop=True
    )
    job_id = uuid.uuid4().hex
    directory = Path("/opt/florama/data/jobs") / job_id
    directory.mkdir(parents=False, exist_ok=False)
    input_path = directory / "input.csv"
    output_path = directory / "submission.csv"
    shutil.copy2(source_path, input_path)
    result = submission(input_path, output_path, args.model)
    out = pd.read_csv(output_path)
    pd.testing.assert_frame_equal(expected, out[["anon_polygon_id", "date"]])
    assert list(out.columns) == ["anon_polygon_id", "date", "primary_ndvi_true"]
    assert not out.duplicated(["anon_polygon_id", "date"]).any()
    assert (
        np.isfinite(out.primary_ndvi_true).all()
        and out.primary_ndvi_true.between(-1, 1).all()
    )
    receipt = {
        "jobId": job_id,
        "rows": len(out),
        "modelSha256": hashlib.sha256(Path(args.model).read_bytes()).hexdigest(),
        "inputSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "outputSha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "output": str(output_path),
        "modelVersion": "source-" + args.version,
    }
    result.update(
        {"modelVersion": receipt["modelVersion"], "modelSha256": receipt["modelSha256"]}
    )
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO jobs(id,user_id,kind,payload,status,progress,message,result,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                source["user_id"],
                "batch",
                dumps({"input": str(input_path), "output": str(output_path)}),
                "done",
                100,
                "Готово · модель " + args.version,
                dumps(result),
                now,
                now,
            ),
        )
    Path(args.receipt).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
