"""Отдельный процесс очереди: веб-запрос не ждёт чтения спутниковых растров."""

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from store import transaction, migrate, dumps
from providers import scenes, weather
from satellite import analyze_scene
from analysis import build_analysis
from reconstruction import submission

logger = logging.getLogger("florama.worker")


def update(job_id, progress, message):
    with transaction() as c:
        c.execute(
            "UPDATE jobs SET progress=?,message=?,updated_at=? WHERE id=?",
            (progress, message, int(time.time()), job_id),
        )


def monitor(job):
    payload = json.loads(job["payload"])
    with transaction() as c:
        row = c.execute(
            "SELECT * FROM polygons WHERE id=? AND user_id=?",
            (job["polygon_id"], job["user_id"]),
        ).fetchone()
        pref = c.execute(
            "SELECT settings FROM preferences WHERE user_id=?", (job["user_id"],)
        ).fetchone()
    if not row:
        raise ValueError("Участок удалён.")
    geometry = json.loads(row["geometry"])
    settings = json.loads(pref["settings"]) if pref else {}
    start, end = payload["start"], payload["end"]
    warnings = []
    catalog = []
    selected = []
    update(job["id"], 3, "Поиск Sentinel-2 и метеоданных")
    for years_ago in range(3):
        year_start = date.fromisoformat(start)
        year_end = date.fromisoformat(end)
        a = (
            year_start.replace(
                year=year_start.year - years_ago, day=min(year_start.day, 28)
            ).isoformat()
            if years_ago
            else start
        )
        b = (
            year_end.replace(
                year=year_end.year - years_ago, day=min(year_end.day, 28)
            ).isoformat()
            if years_ago
            else end
        )
        try:
            items, info = scenes(geometry, a, b, limit=18 if not years_ago else 10)
            selected.extend([(v, years_ago) for v in items])
            catalog.append({"start": a, "end": b, **info})
        except Exception as exc:
            warnings.append(f"Каталог Sentinel-2 {a}–{b}: {type(exc).__name__}.")
            logger.warning(
                "catalog_failed job_id=%s type=%s", job["id"], type(exc).__name__
            )
    try:
        meteo = weather(row["latitude"], row["longitude"], start, end)
    except Exception as exc:
        meteo = []
        warnings.append(
            "Погодный сервис недоступен, спутниковый анализ сохранён без метеоконтекста."
        )
        logger.warning(
            "weather_failed job_id=%s type=%s", job["id"], type(exc).__name__
        )
    observations = []
    history = []
    done = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(analyze_scene, item, geometry, age == 0): (item, age)
            for item, age in selected
        }
        for future in as_completed(futures):
            item, age = futures[future]
            try:
                result = future.result()
                (history if age else observations).append(result)
            except Exception as exc:
                warnings.append(f"Сцена {item['id']} недоступна: {type(exc).__name__}.")
                logger.warning(
                    "scene_failed job_id=%s scene=%s type=%s",
                    job["id"],
                    item["id"],
                    type(exc).__name__,
                )
            done += 1
            update(
                job["id"],
                10 + int(75 * done / max(1, len(selected))),
                f"Обработано снимков: {done}/{len(selected)}",
            )
    observations.sort(key=lambda x: x["date"])
    history.sort(key=lambda x: x["date"])
    if not observations and not meteo:
        raise RuntimeError(
            "Источники не вернули данные. Проверьте период и повторите анализ позже."
        )
    update(job["id"], 90, "Восстановление ряда и объяснение аномалий")
    result = build_analysis(
        observations,
        history,
        meteo,
        start,
        end,
        settings.get("restore", True),
        settings.get("anomaly", True),
    )
    result.update(
        {
            "polygonId": row["id"],
            "polygonName": row["name"],
            "geometry": geometry,
            "areaHa": row["area_ha"],
            "start": start,
            "end": end,
            "weather": meteo,
            "observations": observations,
            "history": history,
            "warnings": warnings,
            "catalog": catalog,
            "createdAt": int(time.time()),
            "provenance": {
                "satellite": "ESA Sentinel-2 L2A; Earth Search sentinel-2-l2a",
                "bands": ["B02", "B04", "B05", "B08", "B8A", "B11", "B12", "SCL"],
                "mask": "SCL 4,5,6; valid coverage >=25%; at least 3 pixels",
                "scale": "raster:bands scale/offset per scene",
                "aggregation": "median valid pixels; 20m or bounded coarser grid",
                "weather": "Open-Meteo ERA5; recent dates operational models; UTC",
                "reference": "two previous years, same seasonal window; median ±22 day-of-year",
                "sampling": catalog,
            },
        }
    )
    analysis_id = uuid.uuid4().hex
    with transaction() as c:
        c.execute(
            "INSERT INTO analyses VALUES (?,?,?,?,?)",
            (analysis_id, row["id"], job["id"], dumps(result), int(time.time())),
        )
    return {
        "analysisId": analysis_id,
        "summary": result["summary"],
        "warnings": len(warnings),
    }


def run_job(job):
    try:
        if job["kind"] == "monitor":
            result = monitor(job)
        elif job["kind"] == "batch":
            payload = json.loads(job["payload"])
            update(job["id"], 10, "Чтение CSV и восстановление контрольных точек")
            result = submission(payload["input"], payload["output"])
        else:
            raise ValueError("Неизвестный тип задания.")
        with transaction() as c:
            c.execute(
                "UPDATE jobs SET status='done',progress=100,message='Готово',result=?,updated_at=? WHERE id=?",
                (dumps(result), int(time.time()), job["id"]),
            )
            c.execute(
                "INSERT INTO events(user_id,kind,message,created_at) VALUES (?,?,?,?)",
                (job["user_id"], "analysis", "Анализ завершён", int(time.time())),
            )
    except Exception as exc:
        logger.exception("job_failed job_id=%s type=%s", job["id"], type(exc).__name__)
        message = (
            str(exc)[:240]
            if isinstance(exc, ValueError)
            else "Не удалось завершить обработку. Повторите задачу; подробности в серверном журнале по ID."
        )
        with transaction() as c:
            c.execute(
                "UPDATE jobs SET status='error',message=?,updated_at=? WHERE id=?",
                (message, int(time.time()), job["id"]),
            )


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    migrate()
    with transaction() as c:
        # Один systemd worker; после перезапуска завершённые результаты не теряются.
        c.execute(
            "UPDATE jobs SET status='queued',message='Возобновлено после перезапуска' WHERE status='running'"
        )
    while True:
        with transaction(immediate=True) as c:
            job = c.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if job:
                c.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?",
                    (int(time.time()), job["id"]),
                )
        if job:
            run_job(job)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()
