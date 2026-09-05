import hashlib
import logging
import os
import secrets
import smtplib
import sqlite3
import time
from email.message import EmailMessage
from functools import wraps

from flask import Flask, g, jsonify, request
from flask_cors import CORS

DB_PATH = os.getenv("DB_PATH", "/opt/florama/data/florama.sqlite3")
CODE_TTL = 300
MAX_ATTEMPTS = 5
APP_ORIGIN = os.getenv("APP_ORIGIN", "https://florama.space")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [APP_ORIGIN, "http://florama.space", "https://florama.space", "http://www.florama.space", "https://www.florama.space", "http://crewloom.ru", "https://crewloom.ru", "http://www.crewloom.ru", "https://www.crewloom.ru"]}}, supports_credentials=False)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s request_id=%(request_id)s %(message)s")
logger = logging.getLogger("florama")


class RequestContext(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(g, "request_id", "-")
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(RequestContext())


@app.before_request
def log_request():
    g.request_id = secrets.token_hex(8)
    logger.info("%s %s origin=%s", request.method, request.path, request.headers.get("Origin", "-"))


@app.after_request
def log_response(response):
    response.headers["X-Request-ID"] = g.get("request_id", "-")
    logger.info("response status=%s", response.status_code)
    return response


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    logger.exception("unhandled_error type=%s", type(error).__name__)
    return jsonify(error="Внутренняя ошибка сервера.", requestId=g.get("request_id", "-")), 500


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL DEFAULT '',
        last_name TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS codes (
        email TEXT PRIMARY KEY,
        code_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_sent_at INTEGER NOT NULL
    )""")
    conn.commit()
    return conn


def normalize_email(value):
    value = (value or "").strip().lower()
    return value if "@" in value and len(value) <= 254 else None


def send_email(email, code):
    message = EmailMessage()
    sender = os.environ["SMTP_USER"]
    message["From"] = os.getenv("SMTP_FROM", sender)
    message["To"] = email
    message["Subject"] = f"{code} — код подтверждения FLORAMA"
    message.set_content(f"Ваш код подтверждения FLORAMA: {code}\n\nКод действует 5 минут.")
    message.add_alternative(f"<p>Ваш код подтверждения FLORAMA:</p><h1>{code}</h1><p>Код действует 5 минут.</p>", subtype="html")
    port = int(os.getenv("SMTP_PORT", "2525"))
    if port == 465:
        smtp = smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.spaceweb.ru"), port, timeout=15)
    else:
        smtp = smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.spaceweb.ru"), port, timeout=15)
    with smtp:
        smtp.ehlo()
        if port != 25:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(sender, os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


@app.post("/api/auth/send-code")
def send_code():
    payload = request.get_json(silent=True) or {}
    email = normalize_email(payload.get("email"))
    mode = payload.get("mode", "login")
    if not email or mode not in {"login", "register"}:
        return jsonify(error="Введите корректные данные."), 400
    now = int(time.time())
    conn = db()
    user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if mode == "login" and not user:
        conn.close()
        return jsonify(error="Аккаунт с этой почтой не найден."), 404
    if mode == "register" and user:
        conn.close()
        return jsonify(error="Аккаунт уже существует. Войдите по коду."), 409
    previous = conn.execute("SELECT last_sent_at FROM codes WHERE email = ?", (email,)).fetchone()
    if previous and now - previous["last_sent_at"] < 60:
        conn.close()
        return jsonify(error="Повторно отправить код можно через минуту."), 429
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = hashlib.sha256(code.encode()).hexdigest()
    conn.execute("INSERT OR REPLACE INTO codes VALUES (?, ?, ?, 0, ?)", (email, digest, now + CODE_TTL, now))
    conn.commit()
    conn.close()
    try:
        send_email(email, code)
    except Exception:
        with db() as rollback:
            rollback.execute("DELETE FROM codes WHERE email = ?", (email,))
        app.logger.exception("SMTP send failed")
        return jsonify(error="Не удалось отправить письмо."), 502
    return jsonify(message="Код отправлен.")


@app.post("/api/auth/verify-code")
def verify_code():
    payload = request.get_json(silent=True) or {}
    email = normalize_email(payload.get("email"))
    code = str(payload.get("code", "")).strip()
    mode = payload.get("mode", "login")
    if not email or not code.isdigit() or len(code) != 6:
        return jsonify(error="Введите шестизначный код."), 400
    now = int(time.time())
    conn = db()
    row = conn.execute("SELECT * FROM codes WHERE email = ?", (email,)).fetchone()
    if not row or row["expires_at"] < now or row["attempts"] >= MAX_ATTEMPTS:
        conn.close()
        return jsonify(error="Код недействителен или истёк."), 400
    digest = hashlib.sha256(code.encode()).hexdigest()
    if not secrets.compare_digest(digest, row["code_hash"]):
        conn.execute("UPDATE codes SET attempts = attempts + 1 WHERE email = ?", (email,))
        conn.commit(); conn.close()
        return jsonify(error="Неверный код."), 400
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if mode == "register":
        if user:
            conn.close(); return jsonify(error="Аккаунт уже существует."), 409
        conn.execute("INSERT INTO users(email, first_name, last_name, created_at) VALUES (?, ?, ?, ?)", (email, (payload.get("firstName") or "").strip()[:80], (payload.get("lastName") or "").strip()[:80], now))
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    elif not user:
        conn.close(); return jsonify(error="Аккаунт не найден."), 404
    conn.execute("DELETE FROM codes WHERE email = ?", (email,)); conn.commit(); conn.close()
    token = secrets.token_urlsafe(32)
    return jsonify(token=token, user={"id": user["id"], "email": user["email"], "firstName": user["first_name"], "lastName": user["last_name"]})


@app.get("/api/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    db().close()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
