# FLORAMA — мониторинг сельхозугодий

FLORAMA — веб-сервис для мониторинга полей: пользователь создаёт участок на карте, запускает анализ, а сервер получает сцены ESA Sentinel-2 L2A, метеоархив и строит временной ряд NDVI с оценкой рисков. Фронтенд отображает готовые данные API; обработка снимков и ML выполняются на VPS.

## Что реализовано

- вход и регистрация одноразовым кодом из почты, сессия в `HttpOnly` cookie, CSRF и rate-limit;
- проекты и полигоны в SQLite с проверкой GeoJSON, геодезической площадью и изоляцией данных пользователей;
- поиск адреса и границ через OpenStreetMap, ручной GeoJSON, переход к публичной карте НСПД по кадастровому номеру;
- реальные Sentinel-2 L2A: B02/B04/B05/B08/B8A/B11/B12 и SCL-маска, NDVI, NDMI, NDRE, EVI, BSI, доля валидных пикселей;
- Sentinel-2 используется как спектральный источник, включая NIR и SWIR, а не как RGB-картинка;
- ERA5/Open-Meteo по координатам и диапазону дат;
- сезонный baseline, аномалии растительности, объяснение через осадки и температуру;
- batch-инференс пропусков NDVI и экспорт ровно в формате соревнования;
- очередь задач на сервере, журналы запросов с request-id и журнал ошибок клиента.

## Быстрый запуск

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
export FLORAMA_DATABASE=./florama.sqlite3
export FLORAMA_ENV=development
export FLORAMA_APP_SECRET='replace-with-32-or-more-random-chars'
python -m flask --app backend.app run
```

Отдельно запустить обработчик задач:

```bash
cd backend && python worker.py
```

В production параметры и SMTP находятся только в `/etc/florama.env`, а systemd-сервисы и nginx описаны в `deploy/`.

## ML и файл для организаторов

Обучение выполняется только на строках с известным `primary_ndvi` и искусственно скрывает часть известных точек при валидации:

```bash
python backend/train.py --input data/raw/train_dataset.csv --output backend/models
python backend/infer.py --input data/raw/test_features.csv --output artifacts/submission.csv
```

`submission.csv` содержит **только** строки `is_synthetic_gap=true` и колонки `anon_polygon_id,date,primary_ndvi_true`. Название последней колонки — требование валидатора; её значения являются прогнозами модели.

Для проверки и обучения модели с отдельными экспертами Sentinel-2, Landsat и MODIS:

```bash
OMP_NUM_THREADS=2 python backend/benchmark_sources.py --input data/raw/train_dataset.csv --output artifacts/source_benchmark
OMP_NUM_THREADS=2 python backend/train_sources.py --input data/raw/train_dataset.csv --benchmark artifacts/source_benchmark/report.json --output backend/models --expert-weight 0.5
```

Проверка делит участки на четыре непересекающиеся группы и исключает контрольные участки из обучения и расчёта обучающих признаков. Перед расчётом признаков маскируются все динамические значения контрольной строки. Файлы приватных ответов не используются. Локальный RMSE не является результатом платформы. Формула баллов: `GapScore = 30 * max(0, 1 - RMSE / 0.10)`.

Дополнительная адаптация использует известные значения из входного CSV. Контрольные строки полностью скрываются до обучения. Настройки привязаны к SHA-256 конкретного файла; для остальных файлов применяется общая модель:

```bash
OMP_NUM_THREADS=2 python backend/benchmark_field_adaptation.py --input data/raw/train_dataset.csv --output artifacts/source_benchmark
OMP_NUM_THREADS=2 python backend/train_field_adaptation.py --reference data/raw/train_dataset.csv --input data/raw/test_features.csv --base-model artifacts/base_model.joblib --report artifacts/source_benchmark/field_adaptation_report.json --output backend/models/gap_model.joblib
```

`artifacts/base_model.joblib` — сохранённая копия модели из `train_sources.py`. Результаты адаптации и общей модели сравниваются на одних и тех же скрытых точках. Проверка адаптации предварительно исключает контрольные значения из всех её обучающих масок.

## Научная добросовестность

Показатели почвы (BSI, SWIR/NIR) и риска болезней являются дистанционными индикаторами, не лабораторным анализом и не диагнозом. Кадастровая граница импортируется пользователем через GeoJSON или проверяется на НСПД: сервис не заявляет доступ к закрытому API Росреестра. Подробности — в `docs/RESEARCH.md`.

## Проверка

```bash
pytest backend/tests -q
python tools/smoke_science.py
```

Проверка backend-кандидата v16 на VPS: 18 tests passed. Ранее live Sentinel-2 сцена дала 100% валидных пикселей после SCL-маски и NDVI 0.59862 для тестовой геометрии; этот внешний сбор не перезапускался при настройке модели.

## Источники данных

- ESA Sentinel-2 L2A через Earth Search STAC;
- OpenStreetMap: геокодирование Nominatim, объекты Overpass и тайлы;
- Open-Meteo Historical Weather / ERA5;
- НСПД — пользовательская проверка кадастрового номера.
