"""functions/geoguesser.py - Geoguesser preset management."""

from .db import get_db


def geo_preset_create(
    name: str, coords: str, description: str, difficulty: str
) -> dict:
    """Create a new geoguesser preset."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO geoguesser_presets (name, coords, description, difficulty)
        VALUES (?, ?, ?, ?)
    """,
        (name, coords, description, difficulty),
    )
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return geo_preset_get_by_id(pid)


def geo_preset_search(query: str = "", difficulty: str = "") -> list[dict]:
    """Search geoguesser presets."""
    conn = get_db()
    c = conn.cursor()
    clauses, params = [], []
    if query:
        clauses.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    c.execute(f"SELECT * FROM geoguesser_presets {where} ORDER BY name ASC", params)
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return rows


def geo_preset_get_by_id(preset_id: int) -> dict | None:
    """Get a geoguesser preset by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM geoguesser_presets WHERE id=?", (preset_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    cols = [d[0] for d in c.description]
    return dict(zip(cols, row))


def geo_preset_delete(preset_id: int) -> None:
    """Delete a geoguesser preset."""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM geoguesser_presets WHERE id=?", (preset_id,))
    conn.commit()
    conn.close()
