from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from parttwin.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    part_number TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    family TEXT NOT NULL,
    function_code TEXT NOT NULL,
    function_label TEXT NOT NULL,
    voltage TEXT,
    connector TEXT,
    length_mm REAL,
    width_mm REAL,
    height_mm REAL,
    mounting TEXT,
    ip_rating TEXT,
    channels INTEGER,
    io_type TEXT,
    region TEXT,
    unit_cost REAL,
    availability TEXT,
    description TEXT,
    missing_fields TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS datasheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL,
    body TEXT NOT NULL,
    FOREIGN KEY (part_number) REFERENCES parts(part_number)
);

CREATE TABLE IF NOT EXISTS investigations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    original_part TEXT,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vault_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_part TEXT NOT NULL,
    recommended_part TEXT,
    verdict TEXT NOT NULL,
    engineer_name TEXT NOT NULL,
    engineer_notes TEXT,
    investigation_id INTEGER,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(db_path: Path | None = None):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    missing = d.get("missing_fields")
    if isinstance(missing, str) and missing:
        try:
            d["missing_fields"] = json.loads(missing)
        except json.JSONDecodeError:
            d["missing_fields"] = []
    elif not missing:
        d["missing_fields"] = []
    return d


def get_part(part_number: str, db_path: Path | None = None) -> dict | None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM parts WHERE part_number = ?",
            (part_number.upper(),),
        ).fetchone()
    return row_to_dict(row)


def list_parts(db_path: Path | None = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM parts ORDER BY part_number").fetchall()
    return [row_to_dict(r) for r in rows]


def get_datasheets(part_number: str, db_path: Path | None = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM datasheets WHERE part_number = ? ORDER BY id",
            (part_number.upper(),),
        ).fetchall()
    return [dict(r) for r in rows]


def search_parts_keyword(query: str, db_path: Path | None = None) -> list[dict]:
    q = f"%{query.strip()}%"
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM parts
            WHERE part_number LIKE ?
               OR name LIKE ?
               OR family LIKE ?
               OR function_label LIKE ?
               OR description LIKE ?
               OR connector LIKE ?
               OR voltage LIKE ?
            ORDER BY part_number
            """,
            (q, q, q, q, q, q, q),
        ).fetchall()
    return [row_to_dict(r) for r in rows]
