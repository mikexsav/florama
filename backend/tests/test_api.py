import json
import io
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

GEOM = {
    "type": "Polygon",
    "coordinates": [
        [[39.70, 47.30], [39.71, 47.30], [39.71, 47.31], [39.70, 47.31], [39.70, 47.30]]
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    database = str(tmp_path / "test.sqlite3")
    monkeypatch.setenv("DB_PATH", database)
    sent = {}
    app = create_app(
        {
            "TESTING": True,
            "DB_PATH": database,
            "DATA_DIR": str(tmp_path),
            "SECRET_KEY": "s" * 64,
            "COOKIE_SECURE": False,
            "MAIL_SENDER": lambda mail, code: sent.update({mail: code}),
        }
    )
    return app, sent


def register(env, email="one@example.com"):
    app, sent = env
    client = app.test_client()
    assert (
        client.post(
            "/api/auth/send-code", json={"email": email, "mode": "register"}
        ).status_code
        == 200
    )
    r = client.post(
        "/api/auth/verify-code",
        json={
            "email": email,
            "mode": "register",
            "code": sent[email],
            "firstName": "Тест",
            "lastName": "Пользователь",
        },
    )
    assert r.status_code == 200, r.json
    return client, {"X-CSRF-Token": r.json["csrfToken"]}


def test_fixed_otp_is_available_only_in_development(tmp_path):
    database = str(tmp_path / "development.sqlite3")
    app = create_app(
        {
            "TESTING": True,
            "DB_PATH": database,
            "DATA_DIR": str(tmp_path),
            "SECRET_KEY": "s" * 64,
            "COOKIE_SECURE": False,
            "FLORAMA_ENV": "development",
            "DEV_OTP_CODE": "000000",
        }
    )
    client = app.test_client()
    email = "docker-review@example.com"
    assert (
        client.post(
            "/api/auth/send-code", json={"email": email, "mode": "register"}
        ).status_code
        == 200
    )
    response = client.post(
        "/api/auth/verify-code",
        json={
            "email": email,
            "mode": "register",
            "code": "000000",
            "firstName": "Локальный",
            "lastName": "Эксперт",
        },
    )
    assert response.status_code == 200

    with pytest.raises(RuntimeError, match="только в development"):
        create_app(
            {
                "DB_PATH": str(tmp_path / "production.sqlite3"),
                "SECRET_KEY": "s" * 64,
                "FLORAMA_ENV": "production",
                "DEV_OTP_CODE": "000000",
            }
        )


def test_session_persistence_logout(env):
    client, headers = register(env)
    assert client.get("/api/auth/me").json["user"]["email"] == "one@example.com"
    assert (
        client.patch(
            "/api/profile",
            json={"firstName": "Новое", "lastName": "Имя"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me").json["user"]["firstName"] == "Новое"
    assert client.post("/api/auth/logout", json={}, headers=headers).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_ownership_and_csrf(env):
    a, ha = register(env)
    b, hb = register(env, "two@example.com")
    assert (
        a.post("/api/polygons", json={"name": "Поле", "geometry": GEOM}).status_code
        == 403
    )
    r = a.post("/api/polygons", json={"name": "Поле", "geometry": GEOM}, headers=ha)
    assert r.status_code == 201, r.json
    polygon = r.json["polygon"]
    assert polygon["area_ha"] > 0
    assert len(a.get("/api/polygons").json["polygons"]) == 1
    assert not b.get("/api/polygons").json["polygons"]
    assert b.delete("/api/polygons/" + polygon["id"], headers=hb).status_code == 404
    assert (
        b.post(
            "/api/polygons/" + polygon["id"] + "/analyze", headers=hb, json={}
        ).status_code
        == 404
    )
    assert a.delete("/api/polygons/" + polygon["id"], headers=ha).status_code == 200


def test_otp_mode_and_replay(env):
    app, sent = env
    c = app.test_client()
    mail = "mode@example.com"
    c.post("/api/auth/send-code", json={"email": mail, "mode": "register"})
    assert (
        c.post(
            "/api/auth/verify-code",
            json={"email": mail, "mode": "login", "code": sent[mail]},
        ).status_code
        == 400
    )
    data = {
        "email": mail,
        "mode": "register",
        "code": sent[mail],
        "firstName": "А",
        "lastName": "Б",
    }
    assert c.post("/api/auth/verify-code", json=data).status_code == 200
    assert c.post("/api/auth/verify-code", json=data).status_code == 400


def test_code_attempt_limit(env):
    app, sent = env
    c = app.test_client()
    mail = "limit@example.com"
    c.post("/api/auth/send-code", json={"email": mail, "mode": "register"})
    wrong = "000000" if sent[mail] != "000000" else "111111"
    data = {
        "email": mail,
        "mode": "register",
        "code": wrong,
        "firstName": "А",
        "lastName": "Б",
    }
    for _ in range(5):
        assert c.post("/api/auth/verify-code", json=data).status_code == 400
    data["code"] = sent[mail]
    assert c.post("/api/auth/verify-code", json=data).status_code == 400


def test_errors_and_settings(env):
    c, h = register(env)
    assert c.get("/api/not-a-route").status_code == 404
    assert (
        c.patch("/api/settings", headers=h, json={"restore": False}).json["settings"][
            "restore"
        ]
        is False
    )
    assert c.get("/api/settings").json["settings"]["restore"] is False
    assert (
        c.post(
            "/api/polygons",
            headers=h,
            json={"name": "bad", "geometry": {"type": "Point", "coordinates": [0, 0]}},
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/projects",
            headers={**h, "Origin": "https://evil.example"},
            json={"name": "X"},
        ).status_code
        == 403
    )
    assert c.post("/api/projects", headers=h, json=[]).status_code == 400


def test_jobs_owned_and_dates(env):
    c, h = register(env)
    p = c.post("/api/polygons", headers=h, json={"name": "P", "geometry": GEOM}).json[
        "polygon"
    ]["id"]
    assert (
        c.post(
            f"/api/polygons/{p}/analyze", headers=h, json={"start": "2010-01-01"}
        ).status_code
        == 400
    )
    assert (
        c.post(
            f"/api/polygons/{p}/analyze",
            headers=h,
            json={"start": "2025-05-01", "end": "2025-07-01"},
        ).status_code
        == 202
    )
    assert c.get("/api/jobs").json["jobs"][0]["status"] == "queued"
    assert c.delete("/api/polygons/" + p, headers=h).status_code == 400


def test_research_map_uses_anonymous_schema_without_coordinates(env):
    app, _ = env
    c, _ = register(env)
    directory = Path(app.config["DATA_DIR"]) / "research"
    directory.mkdir()
    (directory / "train_dataset.csv").write_text(
        "anon_polygon_id,date,primary_ndvi,s2_ndvi,s2_evi,s2_ndwi,crop_type\n"
        "AOI-0001,2024-06-01,0.61,0.63,0.41,0.08,пшеница\n"
        "AOI-0002,2024-06-01,0.24,0.26,0.17,-0.12,подсолнечник\n",
        encoding="utf-8",
    )
    response = c.get("/api/research/map?date=2024-06-01&layer=primary_ndvi")
    assert response.status_code == 200, response.json
    assert response.json["spatialMode"] == "anonymous-grid"
    assert response.json["totalAoi"] == 2
    assert response.json["cells"][0]["value"] == 0.61
    assert "координат" in response.json["note"]


def test_polygon_csv_import_is_atomic(env):
    c, h = register(env)
    geometry = json.dumps(GEOM, ensure_ascii=False).replace('"', '""')
    valid = (
        f'name;region;crop;geometry\nПоле 1;Ростовская область;пшеница;"{geometry}"\n'
    )
    r = c.post(
        "/api/polygons/import-csv",
        headers=h,
        data={"file": (io.BytesIO(valid.encode()), "fields.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201, r.json
    assert r.json["created"] == 1
    invalid = "name;west;south;east;north\nПоле 2;39;47;39.00001;47.00001\n"
    r = c.post(
        "/api/polygons/import-csv",
        headers=h,
        data={"file": (io.BytesIO(invalid.encode()), "bad.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert len(c.get("/api/polygons").json["polygons"]) == 1
