from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(os.getenv("HIDROGESTOR_DB_PATH", BASE_DIR / "data" / "hidrogestor.db"))
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def connection(db_path: str | Path | None = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None, drop_existing: bool = False) -> Path:
    path = resolve_db_path(db_path)
    with connection(path) as conn:
        if drop_existing:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            ).fetchall()
            for table in tables:
                conn.execute(f"DROP TABLE IF EXISTS {table['name']};")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
    return path


def execute(sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None, db_path: str | Path | None = None) -> int:
    with connection(db_path) as conn:
        cur = conn.execute(sql, params or {})
        return int(cur.lastrowid)


def executemany(sql: str, rows: Iterable[dict[str, Any] | tuple[Any, ...]], db_path: str | Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.executemany(sql, list(rows))


def fetch_all(sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None, db_path: str | Path | None = None) -> list[sqlite3.Row]:
    with connection(db_path) as conn:
        return conn.execute(sql, params or {}).fetchall()


def fetch_one(sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None, db_path: str | Path | None = None) -> sqlite3.Row | None:
    with connection(db_path) as conn:
        return conn.execute(sql, params or {}).fetchone()


def read_df(sql: str, params: dict[str, Any] | None = None, db_path: str | Path | None = None) -> pd.DataFrame:
    with connection(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def list_fazendas(db_path: str | Path | None = None) -> pd.DataFrame:
    return read_df("SELECT * FROM fazenda ORDER BY nome", db_path=db_path)


def list_blocos(db_path: str | Path | None = None) -> pd.DataFrame:
    return read_df(
        """
        SELECT b.*, f.nome AS fazenda_nome
        FROM bloco b
        JOIN fazenda f ON f.id = b.fazenda_id
        ORDER BY f.nome, b.nome
        """,
        db_path=db_path,
    )


def list_talhoes(db_path: str | Path | None = None) -> pd.DataFrame:
    return read_df(
        """
        SELECT t.*, b.nome AS bloco_nome, f.nome AS fazenda_nome, f.id AS fazenda_id
        FROM talhao t
        JOIN bloco b ON b.id = t.bloco_id
        JOIN fazenda f ON f.id = b.fazenda_id
        ORDER BY f.nome, b.nome, t.codigo
        """,
        db_path=db_path,
    )


def list_sensores(db_path: str | Path | None = None) -> pd.DataFrame:
    return read_df(
        """
        SELECT s.*, t.codigo AS talhao_codigo, t.nome AS talhao_nome,
               b.nome AS bloco_nome, f.nome AS fazenda_nome
        FROM sensores s
        JOIN talhao t ON t.id = s.talhao_id
        JOIN bloco b ON b.id = t.bloco_id
        JOIN fazenda f ON f.id = b.fazenda_id
        ORDER BY f.nome, b.nome, t.codigo, s.tipo
        """,
        db_path=db_path,
    )
