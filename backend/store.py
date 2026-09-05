"""SQLite с транзакциями, миграциями без удаления существующих аккаунтов."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(path=None):
    path = path or os.getenv("DB_PATH", "/opt/florama/data/florama.sqlite3")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def transaction(path=None, immediate=False):
    conn = connect(path)
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(path=None):
    with transaction(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
          first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS codes (
          email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, last_sent_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS preferences (
          user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          settings TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name TEXT NOT NULL, region TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS polygons (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
          name TEXT NOT NULL, region TEXT NOT NULL DEFAULT '', crop TEXT NOT NULL DEFAULT '',
          geometry TEXT NOT NULL, area_ha REAL NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
          source TEXT NOT NULL, cadastral_number TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS polygons_owner ON polygons(user_id);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          polygon_id TEXT REFERENCES polygons(id) ON DELETE CASCADE, kind TEXT NOT NULL,
          payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '', result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS analyses (
          id TEXT PRIMARY KEY, polygon_id TEXT NOT NULL REFERENCES polygons(id) ON DELETE CASCADE,
          job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL, result TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS analyses_polygon ON analyses(polygon_id, created_at);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, message TEXT NOT NULL, request_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at INTEGER NOT NULL);
        """)
        columns = {row["name"] for row in c.execute("PRAGMA table_info(codes)")}
        if "mode" not in columns:
            c.execute(
                "ALTER TABLE codes ADD COLUMN mode TEXT NOT NULL DEFAULT 'legacy'"
            )


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
