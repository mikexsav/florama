# FLORAMA — спутниковый мониторинг сельхозугодий

FLORAMA — веб-сервис для работы с сельскохозяйственными участками. Пользователь
сохраняет контур, выбирает период, а сервер получает снимки ESA Sentinel-2 и
метеоданные, рассчитывает спектральные индексы, восстанавливает пропуски NDVI и
показывает зоны, требующие полевой проверки. Браузер только отображает результаты:
доступ к внешним источникам, вычисления и хранение выполняются на backend.

## Возможности

- регистрация и вход по одноразовому коду, серверные сессии в `HttpOnly` cookie,
  CSRF-защита и ограничение частоты запросов;
- проекты и приватные участки в SQLite, атомарный импорт CSV, ручное рисование,
  GeoJSON/WKT и прямоугольник из координат;
- поиск адресов и готовых сельхозконтуров через OpenStreetMap;
- Sentinel-2 L2A: B02, B04, B05, B08, B8A, B11, B12 и облачная SCL-маска;
- NDVI, EVI, NDMI, NDRE, BSI и ИК-композит вместо анализа одной RGB-картинки;
- погода по координатам и времени через Open-Meteo Historical Weather/ERA5;
- восстановление временных рядов, сезонная норма, оценка достоверности и сигналы
  стресса растительности без выдачи их за медицинский или лабораторный диагноз;
- фоновая очередь анализа и batch-восстановление CSV с выгрузкой `submission.csv`;
- лаборатория NDVI: просмотр анонимизированного train-набора на воспроизводимой
  сетке, сравнение методов и экспорт результата.

## Быстрый запуск — один шаг

Нужны Git, Docker и Docker Compose v2. Из корня репозитория выполните:

```bash
docker compose up --build
```

Откройте <http://localhost:8080>. Для локальной регистрации используйте любую
корректную почту и код `000000`. Этот код включён только в Docker-конфигурации
`development`; приложение аварийно завершится, если попытаться включить его в
production.

Проверка доступности API:

```bash
curl http://localhost:8080/api/health
```

Остановка стенда:

```bash
docker compose down
```

Чтобы также удалить локальную тестовую БД, выполните `docker compose down -v`.

## Базовый сценарий проверки

1. Откройте сайт, выберите «Создать аккаунт», заполните форму и введите `000000`.
2. Создайте проект на главной странице.
3. Перейдите в «Полигоны» → «Добавить участок» и нарисуйте контур либо найдите
   регион через OpenStreetMap.
4. Для проверки импорта выберите «Импорт CSV» и загрузите
   `docs/examples/polygons.csv`.
5. Откройте участок, задайте прошедший период до 90 дней и нажмите
   «Собрать и проанализировать». Статус фоновой задачи появится ниже.
6. После обработки проверьте вкладки «Карта и ИК», «Динамика NDVI», «Погода» и
   «Достоверность». Для запросов к Sentinel-2 и Open-Meteo нужен интернет.
7. В разделе «Лаборатория NDVI» загрузите тестовый CSV: сервер проверит схему,
   поставит восстановление в очередь и отдаст файл результата.

Пример импорта содержит два небольших прямоугольных участка. Поддерживаемые
колонки: `name`, `region`, `crop`, `cadastral_number` и один из вариантов границы:
`geometry`/`geojson`, `wkt` либо `west,south,east,north`. Разделитель — запятая,
точка с запятой или табуляция; кодировка — UTF-8; максимум 50 участков и 3 МБ.

## Стек

| Слой | Технологии |
| --- | --- |
| Frontend | HTML5, CSS, JavaScript, Leaflet, OpenStreetMap tiles |
| API | Python 3.12, Flask 3, Gunicorn |
| Фоновые задачи | отдельный Python worker, очередь в SQLite |
| Данные | SQLite, GeoJSON, pandas, NumPy |
| Геообработка | Shapely, PyProj, Rasterio |
| ML | scikit-learn, SciPy, LightGBM для исследовательского обучения |
| Источники | Earth Search STAC / ESA Sentinel-2 L2A, OpenStreetMap, Open-Meteo |
| Развёртывание | Docker Compose локально; nginx + systemd на VPS |

Все версии Python-зависимостей зафиксированы в `backend/requirements*.txt`.

## Структура проекта

```text
.
├── backend/
│   ├── app.py                 # HTTP API, валидация и владение сущностями
│   ├── auth.py                # OTP, сессии, CSRF и rate-limit
│   ├── worker.py              # очередь Sentinel-2, метео и batch-инференса
│   ├── providers.py           # клиенты открытых внешних источников
│   ├── satellite.py           # чтение COG, SCL-маска и спектральные индексы
│   ├── analysis.py            # временной ряд, нормы и объяснение аномалий
│   ├── reconstruction.py      # признаки, модели и контракт submission.csv
│   ├── source_model.py        # эксперты Sentinel-2/Landsat/MODIS
│   ├── train*.py              # воспроизводимое обучение и адаптация
│   ├── models/                # рабочий артефакт и отчёты метрик
│   └── tests/                 # API, безопасность, математика и ML-контракт
├── frontend/                  # статический SPA; вычислений и секретов нет
├── deploy/                    # Dockerfile, nginx, systemd и smoke-проверка VPS
├── docs/                      # методика, ограничения и результаты
├── tools/                     # диагностика источников и научный smoke-тест
├── docker-compose.yml         # полностью локальный проверочный стенд
└── README.md
```

## Локальный запуск без Docker

Python 3.12 рекомендуется. В командах ниже `<repo>` — корень репозитория.

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
export FLORAMA_ENV=development
export APP_SECRET=local-development-secret-change-in-production-2026
export APP_ORIGINS=http://localhost:8080
export COOKIE_SECURE=false
export DEV_OTP_CODE=000000
export DB_PATH="$PWD/data/florama.sqlite3"
export DATA_DIR="$PWD/data"
(cd backend && gunicorn --bind 127.0.0.1:8000 'app:create_app()')
```

В другом терминале:

```bash
. .venv/bin/activate
cd backend && python worker.py
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt -r backend\requirements-dev.txt
$env:FLORAMA_ENV='development'
$env:APP_SECRET='local-development-secret-change-in-production-2026'
$env:APP_ORIGINS='http://localhost:8080'
$env:COOKIE_SECURE='false'
$env:DEV_OTP_CODE='000000'
$env:DB_PATH="$PWD\data\florama.sqlite3"
$env:DATA_DIR="$PWD\data"
Set-Location backend
python app.py
```

На Windows worker запускается во втором PowerShell с теми же переменными:
`Set-Location backend; python worker.py`. Статический frontend можно отдать любым
HTTP-сервером с проксированием `/api` на порт 8000; готовая конфигурация находится
в `deploy/nginx.local.conf`, поэтому для полной проверки проще Docker Compose.

## Конфигурация

| Переменная | Назначение |
| --- | --- |
| `APP_SECRET` | секрет подписи HMAC, минимум 32 символа; обязателен |
| `APP_ORIGINS` | разрешённые Origin через запятую |
| `COOKIE_SECURE` | `true` на HTTPS, `false` только локально |
| `DB_PATH` | путь к SQLite |
| `DATA_DIR` | задания, результаты и необязательный research-набор |
| `SMTP_HOST`, `SMTP_PORT` | SMTP-сервер production |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | учётные данные и отправитель OTP |
| `DEV_OTP_CODE` | фиксированный локальный код; только при `FLORAMA_ENV=development` |

Production-шаблон находится в `backend/.env.example`. Секреты и исходные
датасеты не коммитятся.

## Тесты и автоматическая проверка

```bash
python -m pytest backend/tests -q
ruff check backend tools deploy
python tools/smoke_science.py
python -m compileall -q backend tools deploy
```

Тесты проверяют OTP и повторное использование кода, CSRF, изоляцию данных двух
пользователей, геометрию, атомарный CSV-импорт, научные формулы, маскирование
контрольных строк, совместимость старой модели и dataset-bound артефакт.

## Воспроизводимость ML

Положите предоставленные файлы в `data/raw/`:

```text
data/raw/train_dataset.csv
data/raw/test_features.csv
```

Из корня репозитория:

```bash
cd backend
python benchmark_sources.py --input ../data/raw/train_dataset.csv --output ../artifacts/source-benchmark
python train_sources.py --input ../data/raw/train_dataset.csv \
  --benchmark ../artifacts/source-benchmark/report.json --output ../artifacts/model \
  --expert-weight 0.5
python infer.py --input ../data/raw/test_features.csv --output ../artifacts/submission.csv \
  --model ../artifacts/model/gap_model.joblib
```

Дополнительный OOF-стекинг использует видимые значения целевого файла как
контекст и никогда не читает `primary_ndvi` строк с `is_synthetic_gap=True`:

```bash
python train_transductive_stacker.py --input ../data/raw/test_features.csv \
  --base-model ../artifacts/model/gap_model.joblib \
  --cache ../artifacts/oof --output ../artifacts/stacked.csv
python train_covariate_shift_stacker.py --input ../data/raw/test_features.csv \
  --base-model ../artifacts/model/gap_model.joblib --oof-cache ../artifacts/oof \
  --output ../artifacts/covariate-shift.csv
```

Финальный артефакт может хранить проверенный прогноз для точного SHA-256 входного
файла и универсальную модель для любого другого CSV. `package_dataset_release.py`
проверяет хеш, порядок ключей, число строк, диапазон и схему до упаковки. При
несовпадении файла автоматически используется универсальная модель.

Контракт результата: только строки `is_synthetic_gap=True`, без дубликатов,
колонки `anon_polygon_id,date,primary_ndvi_true`, конечные значения в `[-1, 1]`.
Название `primary_ndvi_true` задано валидатором принимающей системы; внутри файла
находятся именно прогнозы.

Seeds, доли масок, SHA-256 входов, версии библиотек и метрики сохраняются в
артефакте и JSON-отчётах. Подробная методика — `docs/RESEARCH.md`, проверенные
публичные результаты — `docs/PUBLIC_RESULTS.md`.

## Данные лаборатории NDVI

Для отображения train-набора поместите его в общий каталог данных:

```bash
docker compose exec api mkdir -p /data/research
docker compose cp data/raw/train_dataset.csv api:/data/research/train_dataset.csv
```

Файл не содержит координат. Поэтому интерфейс честно строит стабильную
анонимизированную сетку AOI, а не выдаёт её за реальные границы полей.

## Развёртывание на VPS

Production использует два systemd-сервиса и nginx:

- `deploy/florama.service` — Gunicorn API на `127.0.0.1:8000`;
- `deploy/florama-worker.service` — фоновая очередь;
- `deploy/nginx.conf` — frontend, `/api`, ограничения загрузки и заголовки;
- `deploy/prepare_env.py` — подготовка `/etc/florama.env` без вывода секретов;
- `deploy/smoke_vps.py` — проверка импортов, БД и SMTP TLS.

Перед запуском заполните `/etc/florama.env` по `backend/.env.example`, установите
unit-файлы, проверьте `nginx -t`, затем включите сервисы. TLS завершается на nginx;
`COOKIE_SECURE=true` обязателен. Конкретные пароли, токены и приватные ключи в
репозитории отсутствуют.

## Научные ограничения

- SCL-маска удаляет облака и тени до агрегации; результат хранит долю пригодных
  пикселей и происхождение данных.
- BSI/SWIR/NIR показывают спектральные свойства и влагосостояние, но не дают без
  лабораторной калибровки точный гумус, кислотность или N/P/K.
- Падение NDVI/NDRE — сигнал для осмотра, а не диагноз болезни: возможны засуха,
  уборка, фаза культуры или ошибка наблюдения.
- Локальная валидация предназначена для выбора метода и не подменяет независимый
  результат внешней платформы. Приватный ground truth в обучении не используется.

Лицензии и условия внешних источников необходимо учитывать при production-
эксплуатации. Сервис ссылается на OpenStreetMap и провайдера тайлов в интерфейсе.
