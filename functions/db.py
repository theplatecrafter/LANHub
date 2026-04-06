"""functions/db.py - Core database operations."""

import sqlite3
from glob_vars import DB_PATH


def get_db():
    """Returns a sqlite3 connection. Caller is responsible for closing it."""
    try:
        # Try to use DI container if available (for testing)
        from dependencies import DI

        return DI.get("get_db")()
    except (ImportError, KeyError):
        # Fall back to direct connection
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # rows behave like dicts
        return conn


def db_get_tables() -> list[str]:
    """Get list of all tables in the database."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def db_get_schema(table: str) -> list[dict]:
    """Get schema/info for a specific table."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        f"PRAGMA table_info({table})"
    )  # table name is safe — validated caller-side
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def db_query(sql: str, params: list = None) -> list:
    """
    Runs a read-only SQL statement and returns rows as dicts.
    Only SELECT statements are permitted.
    """
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    conn = get_db()
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    c = conn.cursor()
    try:
        if params:
            c.execute(sql, params)
        else:
            c.execute(sql)
        rows = [dict(r) for r in c.fetchall()]
        # Don't close in test environment (in-memory DB)
        return rows
    except Exception as e:
        raise ValueError(f"Query failed: {e}")


def db_get_row(table: str, rowid: int):
    """Fetch a single row by rowid. Returns dict or None."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute(f"SELECT * FROM {table} WHERE rowid = ?", (rowid,))
        row = c.fetchone()
        return dict(row) if row else None
    except Exception as e:
        raise ValueError(f"Cannot fetch row: {e}")


def db_insert(table: str, data: dict) -> int:
    """
    Insert a row. data = {col: value, ...} (do NOT include rowid).
    Returns the new rowid.
    """
    if not data:
        raise ValueError("No column data provided.")
    cols = list(data.keys())
    vals = [data[c] for c in cols]
    ph = ", ".join("?" * len(cols))
    col_str = ", ".join(cols)
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(f"INSERT INTO {table} ({col_str}) VALUES ({ph})", vals)
        conn.commit()
        new_id = c.lastrowid
        return new_id
    except Exception as e:
        raise ValueError(f"Insert failed: {e}")


def db_update_row(table: str, rowid: int, data: dict) -> None:
    """
    Update a row by rowid. data = {col: value, ...} for columns to change.
    Skips the rowid column itself if present in data.
    """
    data = {k: v for k, v in data.items() if k.lower() != "rowid"}
    if not data:
        raise ValueError("No columns to update.")
    set_clause = ", ".join(f"{col} = ?" for col in data)
    vals = list(data.values()) + [rowid]
    conn = get_db()
    try:
        conn.execute(f"UPDATE {table} SET {set_clause} WHERE rowid = ?", vals)
        conn.commit()
    except Exception as e:
        raise ValueError(f"Update failed: {e}")


def db_delete_row(table: str, rowid: int) -> None:
    """Delete a row by rowid."""
    conn = get_db()
    try:
        conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
        conn.commit()
    except Exception as e:
        raise ValueError(f"Delete failed: {e}")
