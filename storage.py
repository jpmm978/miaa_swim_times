import csv
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import Entry, Event, EventType, Result, ResultStatus
from timing import format_cs_to_time

DB_PATH = Path("swim_meet.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    """Adds a column to an existing SQLite table if it is not already present."""
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db() -> None:
    """Creates tables if they do not already exist and migrates existing data to multi-meet support."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meets (
                meet_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                team_a TEXT NOT NULL DEFAULT 'Home Team',
                team_b TEXT NOT NULL DEFAULT 'Visiting Team',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meet_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                entry_id TEXT PRIMARY KEY,
                meet_id TEXT NOT NULL DEFAULT 'default_meet',
                event_number INTEGER NOT NULL,
                team_id TEXT NOT NULL,
                athlete_ids TEXT NOT NULL,
                is_exhibition INTEGER NOT NULL,
                relay_letter TEXT,
                heat_number INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                entry_id TEXT PRIMARY KEY,
                watch_time_cs INTEGER,
                backup_times_cs TEXT NOT NULL DEFAULT '[]',
                diving_score REAL,
                status TEXT NOT NULL DEFAULT 'OK',
                official_time_cs INTEGER,
                manual_place INTEGER,
                override_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (entry_id) REFERENCES entries (entry_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS roster (
                team_id TEXT NOT NULL,
                name TEXT NOT NULL,
                gender TEXT NOT NULL,
                PRIMARY KEY (team_id, name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lineups (
                meet_id TEXT NOT NULL DEFAULT 'default_meet',
                event_number INTEGER NOT NULL,
                lane INTEGER NOT NULL,
                team_id TEXT NOT NULL,
                athlete_ids TEXT NOT NULL,
                relay_letter TEXT,
                is_exhibition INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (meet_id, event_number, lane)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meet_signatures (
                meet_id TEXT NOT NULL,
                role_key TEXT NOT NULL,
                signer_name TEXT NOT NULL DEFAULT '',
                signature_data_url TEXT NOT NULL,
                signed_at TEXT NOT NULL,
                PRIMARY KEY (meet_id, role_key)
            )
            """
        )

        _ensure_column(conn, "results", "watch_time_cs", "INTEGER")
        _ensure_column(conn, "results", "backup_times_cs", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "results", "diving_score", "REAL")
        _ensure_column(conn, "results", "status", "TEXT NOT NULL DEFAULT 'OK'")
        _ensure_column(conn, "results", "official_time_cs", "INTEGER")
        _ensure_column(conn, "results", "manual_place", "INTEGER")
        _ensure_column(conn, "results", "override_note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "entries", "meet_id", "TEXT NOT NULL DEFAULT 'default_meet'")
        _ensure_column(conn, "entries", "heat_number", "INTEGER NOT NULL DEFAULT 1")

        lineup_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(lineups)").fetchall()
        }
        if "meet_id" not in lineup_cols:
            conn.execute("ALTER TABLE lineups RENAME TO lineups_old")
            conn.execute(
                """
                CREATE TABLE lineups (
                    meet_id TEXT NOT NULL DEFAULT 'default_meet',
                    event_number INTEGER NOT NULL,
                    lane INTEGER NOT NULL,
                    team_id TEXT NOT NULL,
                    athlete_ids TEXT NOT NULL,
                    relay_letter TEXT,
                    is_exhibition INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (meet_id, event_number, lane)
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO lineups (
                    meet_id, event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                )
                SELECT 'default_meet', event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                FROM lineups_old
                """
            )
            conn.execute("DROP TABLE lineups_old")

        conn.execute(
            "INSERT OR IGNORE INTO meet_meta (key, value) VALUES ('team_a', 'Home Team')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO meet_meta (key, value) VALUES ('team_b', 'Visiting Team')"
        )

        meta_rows = dict(conn.execute("SELECT key, value FROM meet_meta").fetchall())
        legacy_a = meta_rows.get("team_a", "Home Team")
        legacy_b = meta_rows.get("team_b", "Visiting Team")

        conn.execute(
            """
            INSERT OR IGNORE INTO meets (meet_id, title, team_a, team_b, status, created_at, closed_at)
            VALUES ('default_meet', ?, ?, ?, 'ACTIVE', ?, NULL)
            """,
            (f"{legacy_a} vs {legacy_b}", legacy_a, legacy_b, now_iso),
        )

        active_row = conn.execute(
            "SELECT value FROM meet_meta WHERE key = 'active_meet_id'"
        ).fetchone()
        if not active_row:
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', 'default_meet')"
            )


def export_full_backup_json() -> str:
    """Exports all meets, entries, results, rosters, lineups, and signatures as JSON."""
    with _get_conn() as conn:
        payload = {
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "meets": [dict(r) for r in conn.execute("SELECT * FROM meets").fetchall()],
            "meet_meta": [dict(r) for r in conn.execute("SELECT * FROM meet_meta").fetchall()],
            "entries": [dict(r) for r in conn.execute("SELECT * FROM entries").fetchall()],
            "results": [dict(r) for r in conn.execute("SELECT * FROM results").fetchall()],
            "roster": [dict(r) for r in conn.execute("SELECT * FROM roster").fetchall()],
            "lineups": [dict(r) for r in conn.execute("SELECT * FROM lineups").fetchall()],
            "meet_signatures": [
                dict(r) for r in conn.execute("SELECT * FROM meet_signatures").fetchall()
            ],
        }
    return json.dumps(payload, indent=2)


def restore_full_backup_json(raw_json: str) -> tuple[bool, str]:
    """Restores a previously exported backup JSON snapshot into SQLite."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON file: {exc}"

    if not isinstance(data, dict) or "meets" not in data:
        return False, "Backup file is missing required meet data."

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute("DELETE FROM results")
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM lineups")
        conn.execute("DELETE FROM meet_signatures")
        conn.execute("DELETE FROM roster")
        conn.execute("DELETE FROM meets")
        conn.execute("DELETE FROM meet_meta")

        for m in data.get("meets", []):
            conn.execute(
                """
                INSERT INTO meets (meet_id, title, team_a, team_b, status, created_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.get("meet_id") or "default_meet",
                    m.get("title") or "Restored Meet",
                    m.get("team_a") or "Home Team",
                    m.get("team_b") or "Visiting Team",
                    m.get("status") or "ACTIVE",
                    m.get("created_at") or now_iso,
                    m.get("closed_at"),
                ),
            )

        for mm in data.get("meet_meta", []):
            if mm.get("key") is not None and mm.get("value") is not None:
                conn.execute(
                    "INSERT INTO meet_meta (key, value) VALUES (?, ?)",
                    (mm["key"], mm["value"]),
                )

        for r in data.get("roster", []):
            conn.execute(
                "INSERT INTO roster (team_id, name, gender) VALUES (?, ?, ?)",
                (r["team_id"], r["name"], r["gender"]),
            )

        for e in data.get("entries", []):
            conn.execute(
                """
                INSERT INTO entries (
                    entry_id, meet_id, event_number, team_id, athlete_ids, is_exhibition, relay_letter, heat_number
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e["entry_id"],
                    e.get("meet_id") or "default_meet",
                    e["event_number"],
                    e["team_id"],
                    e["athlete_ids"]
                    if isinstance(e["athlete_ids"], str)
                    else json.dumps(e["athlete_ids"]),
                    int(bool(e.get("is_exhibition", 0))),
                    e.get("relay_letter"),
                    int(e.get("heat_number") or 1),
                ),
            )

        for res in data.get("results", []):
            conn.execute(
                """
                INSERT INTO results (
                    entry_id, watch_time_cs, backup_times_cs, diving_score,
                    status, official_time_cs, manual_place, override_note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    res["entry_id"],
                    res.get("watch_time_cs"),
                    res.get("backup_times_cs")
                    if isinstance(res.get("backup_times_cs"), str)
                    else json.dumps(res.get("backup_times_cs") or []),
                    res.get("diving_score"),
                    res.get("status") or "OK",
                    res.get("official_time_cs"),
                    res.get("manual_place"),
                    res.get("override_note") or "",
                ),
            )

        for lu in data.get("lineups", []):
            conn.execute(
                """
                INSERT INTO lineups (
                    meet_id, event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lu.get("meet_id") or "default_meet",
                    lu["event_number"],
                    lu["lane"],
                    lu["team_id"],
                    lu["athlete_ids"]
                    if isinstance(lu["athlete_ids"], str)
                    else json.dumps(lu["athlete_ids"]),
                    lu.get("relay_letter"),
                    int(bool(lu.get("is_exhibition", 0))),
                ),
            )

        for sig in data.get("meet_signatures", []):
            conn.execute(
                """
                INSERT INTO meet_signatures (
                    meet_id, role_key, signer_name, signature_data_url, signed_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    sig["meet_id"],
                    sig["role_key"],
                    sig.get("signer_name") or "",
                    sig["signature_data_url"],
                    sig.get("signed_at") or now_iso,
                ),
            )

    init_db()
    return True, f"Restored {len(data.get('meets', []))} meet(s) from backup."


def save_meet_signature(
    meet_id: str,
    role_key: str,
    signer_name: str,
    signature_data_url: str,
) -> None:
    """Saves or updates an electronic signature (PNG data URL) for a meet role."""
    signed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO meet_signatures (
                meet_id, role_key, signer_name, signature_data_url, signed_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (meet_id, role_key, signer_name.strip(), signature_data_url.strip(), signed_at),
        )


def load_meet_signatures(meet_id: str) -> dict[str, dict]:
    """Returns saved signatures keyed by role_key."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role_key, signer_name, signature_data_url, signed_at
            FROM meet_signatures
            WHERE meet_id = ?
            """,
            (meet_id,),
        ).fetchall()
    return {r["role_key"]: dict(r) for r in rows}


def delete_meet_signature(meet_id: str, role_key: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM meet_signatures WHERE meet_id = ? AND role_key = ?",
            (meet_id, role_key),
        )


def list_meets() -> list[dict]:
    """Returns all saved meets ordered by active status first, then most recently created."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT meet_id, title, team_a, team_b, status, created_at, closed_at
            FROM meets
            ORDER BY CASE WHEN status = 'ACTIVE' THEN 0 ELSE 1 END, created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_meet_id() -> str:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM meet_meta WHERE key = 'active_meet_id'"
        ).fetchone()
        if row and row["value"]:
            exists = conn.execute(
                "SELECT 1 FROM meets WHERE meet_id = ?", (row["value"],)
            ).fetchone()
            if exists:
                return row["value"]
        first = conn.execute("SELECT meet_id FROM meets LIMIT 1").fetchone()
        fallback = first["meet_id"] if first else "default_meet"
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', ?)",
            (fallback,),
        )
        return fallback


def set_active_meet(meet_id: str) -> None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT team_a, team_b FROM meets WHERE meet_id = ?", (meet_id,)
        ).fetchone()
        if not row:
            return
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', ?)",
            (meet_id,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', ?)",
            (row["team_a"],),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', ?)",
            (row["team_b"],),
        )


def create_new_meet(
    meet_id: str,
    title: str,
    team_a: str,
    team_b: str,
    copy_lineups_from_current: bool = False,
) -> str:
    """Creates a new active meet and switches to it."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    clean_a = team_a.strip() or "Home Team"
    clean_b = team_b.strip() or "Visiting Team"
    clean_title = title.strip() or f"{clean_a} vs {clean_b} ({now_iso})"
    prev_meet_id = get_active_meet_id()

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO meets (meet_id, title, team_a, team_b, status, created_at, closed_at)
            VALUES (?, ?, ?, ?, 'ACTIVE', ?, NULL)
            """,
            (meet_id, clean_title, clean_a, clean_b, now_iso),
        )
        if copy_lineups_from_current:
            conn.execute(
                """
                INSERT INTO lineups (
                    meet_id, event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                )
                SELECT ?, event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                FROM lineups
                WHERE meet_id = ?
                """,
                (meet_id, prev_meet_id),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', ?)",
            (meet_id,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', ?)", (clean_a,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', ?)", (clean_b,)
        )
    return meet_id


def set_meet_status(meet_id: str, status: str) -> None:
    """Marks a meet as CLOSED or REOPENED ('ACTIVE')."""
    normalized = "CLOSED" if status.upper() == "CLOSED" else "ACTIVE"
    closed_at = datetime.now().strftime("%Y-%m-%d %H:%M") if normalized == "CLOSED" else None
    with _get_conn() as conn:
        conn.execute(
            "UPDATE meets SET status = ?, closed_at = ? WHERE meet_id = ?",
            (normalized, closed_at, meet_id),
        )


def rename_meet(meet_id: str, new_title: str) -> None:
    clean_title = new_title.strip()
    if not clean_title:
        return
    with _get_conn() as conn:
        conn.execute(
            "UPDATE meets SET title = ? WHERE meet_id = ?",
            (clean_title, meet_id),
        )


def delete_meet(meet_id: str) -> None:
    """Deletes a saved meet and its entries, results, lineups, and signatures."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM results WHERE entry_id IN (SELECT entry_id FROM entries WHERE meet_id = ?)",
            (meet_id,),
        )
        conn.execute("DELETE FROM entries WHERE meet_id = ?", (meet_id,))
        conn.execute("DELETE FROM lineups WHERE meet_id = ?", (meet_id,))
        conn.execute("DELETE FROM meet_signatures WHERE meet_id = ?", (meet_id,))
        conn.execute("DELETE FROM meets WHERE meet_id = ?", (meet_id,))

        remaining = conn.execute(
            "SELECT meet_id, team_a, team_b FROM meets ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if remaining:
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', ?)",
                (remaining["meet_id"],),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', ?)",
                (remaining["team_a"],),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', ?)",
                (remaining["team_b"],),
            )
        else:
            conn.execute(
                """
                INSERT INTO meets (meet_id, title, team_a, team_b, status, created_at, closed_at)
                VALUES ('default_meet', 'Home Team vs Visiting Team', 'Home Team', 'Visiting Team', 'ACTIVE', ?, NULL)
                """,
                (now_iso,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('active_meet_id', 'default_meet')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', 'Home Team')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', 'Visiting Team')"
            )


def load_team_names(meet_id: Optional[str] = None) -> tuple[str, str]:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT team_a, team_b FROM meets WHERE meet_id = ?", (target_id,)
        ).fetchone()
        if row:
            return row["team_a"], row["team_b"]
        rows = dict(conn.execute("SELECT key, value FROM meet_meta").fetchall())
    return rows.get("team_a", "Home Team"), rows.get("team_b", "Visiting Team")


def save_team_names(team_a: str, team_b: str, meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    old_a, old_b = load_team_names(target_id)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE meets SET team_a = ?, team_b = ? WHERE meet_id = ?",
            (team_a, team_b, target_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', ?)", (team_a,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', ?)", (team_b,)
        )
        if old_a != team_a:
            conn.execute("UPDATE roster SET team_id = ? WHERE team_id = ?", (team_a, old_a))
            conn.execute(
                "UPDATE entries SET team_id = ? WHERE meet_id = ? AND team_id = ?",
                (team_a, target_id, old_a),
            )
            conn.execute(
                "UPDATE lineups SET team_id = ? WHERE meet_id = ? AND team_id = ?",
                (team_a, target_id, old_a),
            )
        if old_b != team_b:
            conn.execute("UPDATE roster SET team_id = ? WHERE team_id = ?", (team_b, old_b))
            conn.execute(
                "UPDATE entries SET team_id = ? WHERE meet_id = ? AND team_id = ?",
                (team_b, target_id, old_b),
            )
            conn.execute(
                "UPDATE lineups SET team_id = ? WHERE meet_id = ? AND team_id = ?",
                (team_b, target_id, old_b),
            )


def save_entry_and_result(entry: Entry, result: Result, meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO entries (
                entry_id, meet_id, event_number, team_id, athlete_ids, is_exhibition, relay_letter, heat_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.entry_id,
                target_id,
                entry.event_number,
                entry.team_id,
                json.dumps(entry.athlete_ids),
                int(entry.is_exhibition),
                entry.relay_letter,
                int(getattr(entry, "heat_number", 1)),
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO results (
                entry_id, watch_time_cs, backup_times_cs, diving_score,
                status, official_time_cs, manual_place, override_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.entry_id,
                result.watch_time_cs,
                json.dumps(result.backup_times_cs),
                result.diving_score,
                result.status.value,
                result.official_time_cs,
                result.manual_place,
                result.override_note,
            ),
        )


def update_entry_and_result(entry: Entry, result: Result) -> None:
    """Updates an existing entry and its result in place without changing entry_id or meet_id."""
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE entries
            SET team_id = ?, athlete_ids = ?, is_exhibition = ?, relay_letter = ?, heat_number = ?
            WHERE entry_id = ?
            """,
            (
                entry.team_id,
                json.dumps(entry.athlete_ids),
                int(entry.is_exhibition),
                entry.relay_letter,
                int(getattr(entry, "heat_number", 1)),
                entry.entry_id,
            ),
        )
        conn.execute(
            """
            UPDATE results
            SET watch_time_cs = ?,
                backup_times_cs = ?,
                diving_score = ?,
                status = ?,
                official_time_cs = ?,
                manual_place = ?,
                override_note = ?
            WHERE entry_id = ?
            """,
            (
                result.watch_time_cs,
                json.dumps(result.backup_times_cs),
                result.diving_score,
                result.status.value,
                result.official_time_cs,
                result.manual_place,
                result.override_note,
                result.entry_id,
            ),
        )


def update_result_override(
    entry_id: str,
    manual_place: Optional[int],
    override_note: str = "",
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE results
            SET manual_place = ?, override_note = ?
            WHERE entry_id = ?
            """,
            (manual_place, override_note, entry_id),
        )


def delete_entry_and_result(entry_id: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM results WHERE entry_id = ?", (entry_id,))
        conn.execute("DELETE FROM entries WHERE entry_id = ?", (entry_id,))


def load_all_data(meet_id: Optional[str] = None) -> tuple[list[Entry], list[Result]]:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        entry_rows = conn.execute(
            "SELECT * FROM entries WHERE meet_id = ?", (target_id,)
        ).fetchall()
        result_rows = conn.execute(
            """
            SELECT r.*
            FROM results r
            INNER JOIN entries e ON r.entry_id = e.entry_id
            WHERE e.meet_id = ?
            """,
            (target_id,),
        ).fetchall()

    entries: list[Entry] = []
    for r in entry_rows:
        e_keys = set(r.keys())
        heat_val = r["heat_number"] if "heat_number" in e_keys and r["heat_number"] is not None else 1
        entries.append(
            Entry(
                entry_id=r["entry_id"],
                event_number=r["event_number"],
                team_id=r["team_id"],
                athlete_ids=json.loads(r["athlete_ids"]),
                is_exhibition=bool(r["is_exhibition"]),
                relay_letter=r["relay_letter"],
                heat_number=int(heat_val),
            )
        )

    results: list[Result] = []
    for r in result_rows:
        keys = set(r.keys())
        watch_cs = r["watch_time_cs"] if "watch_time_cs" in keys else None
        backups_raw = r["backup_times_cs"] if "backup_times_cs" in keys else "[]"
        backups_cs = json.loads(backups_raw) if backups_raw else []
        diving_score = r["diving_score"] if "diving_score" in keys else None
        status_val = r["status"] if "status" in keys and r["status"] else "OK"
        official_cs = r["official_time_cs"] if "official_time_cs" in keys else None
        manual_place = r["manual_place"] if "manual_place" in keys else None
        override_note = (
            r["override_note"] if "override_note" in keys and r["override_note"] else ""
        )

        results.append(
            Result(
                entry_id=r["entry_id"],
                watch_time_cs=watch_cs,
                backup_times_cs=backups_cs,
                diving_score=diving_score,
                status=ResultStatus(status_val),
                official_time_cs=official_cs,
                manual_place=manual_place,
                override_note=override_note,
            )
        )

    return entries, results


def save_lineups(lineup_rows: list[dict], meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        for row in lineup_rows:
            ev_num = row["event_number"]
            lane = row["lane"]
            athletes = row.get("athlete_ids") or []
            if athletes:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO lineups (
                        meet_id, event_number, lane, team_id, athlete_ids, relay_letter, is_exhibition
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_id,
                        ev_num,
                        lane,
                        row["team_id"],
                        json.dumps(athletes),
                        row.get("relay_letter"),
                        int(bool(row.get("is_exhibition", False))),
                    ),
                )
            else:
                conn.execute(
                    "DELETE FROM lineups WHERE meet_id = ? AND event_number = ? AND lane = ?",
                    (target_id, ev_num, lane),
                )


def load_lineups(meet_id: Optional[str] = None) -> dict[tuple[int, int], dict]:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM lineups WHERE meet_id = ?", (target_id,)
        ).fetchall()

    lineups: dict[tuple[int, int], dict] = {}
    for r in rows:
        lineups[(r["event_number"], r["lane"])] = {
            "event_number": r["event_number"],
            "lane": r["lane"],
            "team_id": r["team_id"],
            "athlete_ids": json.loads(r["athlete_ids"]),
            "relay_letter": r["relay_letter"],
            "is_exhibition": bool(r["is_exhibition"]),
        }
    return lineups


def clear_lineups(meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        conn.execute("DELETE FROM lineups WHERE meet_id = ?", (target_id,))


def clear_event(event_number: int, meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        conn.execute(
            """
            DELETE FROM results
            WHERE entry_id IN (
                SELECT entry_id FROM entries WHERE meet_id = ? AND event_number = ?
            )
            """,
            (target_id, event_number),
        )
        conn.execute(
            "DELETE FROM entries WHERE meet_id = ? AND event_number = ?",
            (target_id, event_number),
        )


def clear_all(meet_id: Optional[str] = None) -> None:
    target_id = meet_id or get_active_meet_id()
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM results WHERE entry_id IN (SELECT entry_id FROM entries WHERE meet_id = ?)",
            (target_id,),
        )
        conn.execute("DELETE FROM entries WHERE meet_id = ?", (target_id,))


def parse_roster_csv(file_bytes: bytes) -> list[tuple[str, str]]:
    """Flexibly parses a roster CSV (with or without headers) into [(name, 'F'|'M'), ...]."""
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    rows = list(csv.reader(io.StringIO(text)))
    swimmers: list[tuple[str, str]] = []

    for idx, row in enumerate(rows):
        cells = [c.strip() for c in row if c.strip()]
        if len(cells) < 2:
            continue

        if idx == 0 and cells[0].lower() in ("name", "swimmer", "athlete", "last", "last name"):
            continue

        raw_gender = cells[-1].upper()
        name = " ".join(cells[:-1]).strip()

        if raw_gender.startswith(("F", "G")):
            gender = "F"
        elif raw_gender.startswith(("M", "B")):
            gender = "M"
        else:
            continue

        if name:
            swimmers.append((name, gender))

    return swimmers


def save_roster(team_id: str, swimmers: list[tuple[str, str]]) -> None:
    """Replaces the saved roster for a given team."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM roster WHERE team_id = ?", (team_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO roster (team_id, name, gender) VALUES (?, ?, ?)",
            [(team_id, name, gender) for name, gender in swimmers],
        )


def load_rosters() -> dict[tuple[str, str], list[str]]:
    """Returns a lookup dict mapping (team_id, gender) -> sorted list of swimmer names."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT team_id, name, gender FROM roster ORDER BY name ASC"
        ).fetchall()

    rosters: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        key = (r["team_id"], r["gender"])
        rosters.setdefault(key, []).append(r["name"])
    return rosters


def export_meet_csv(
    events: list[Event],
    entries: list[Entry],
    results: list[Result],
) -> str:
    """Returns a CSV string of all scored meet results ordered by event and place."""
    events_by_num = {e.event_number: e for e in events}
    entries_by_id = {e.entry_id: e for e in entries}

    sorted_results = sorted(
        results,
        key=lambda r: (
            entries_by_id[r.entry_id].event_number,
            r.place is None,
            r.place or 999,
        ),
    )

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Event #",
            "Gender",
            "Event Name",
            "Place",
            "Team",
            "Participant",
            "Official Time / Score",
            "Status",
            "Exhibition",
            "Points",
        ],
    )
    writer.writeheader()

    for res in sorted_results:
        ent = entries_by_id[res.entry_id]
        ev = events_by_num[ent.event_number]

        if ev.event_type == EventType.DIVING:
            perf = f"{res.diving_score:.2f}" if res.diving_score is not None else ""
        else:
            perf = (
                format_cs_to_time(res.official_time_cs)
                if res.official_time_cs is not None
                else ""
            )

        writer.writerow(
            {
                "Event #": ev.event_number,
                "Gender": "Girls" if ev.gender == "F" else "Boys",
                "Event Name": ev.name,
                "Place": res.place if res.place is not None else "",
                "Team": ent.team_id,
                "Participant": ", ".join(ent.athlete_ids),
                "Official Time / Score": perf,
                "Status": res.status.value,
                "Exhibition": "Yes" if ent.is_exhibition else "No",
                "Points": f"{res.points:g}",
            }
        )

    return output.getvalue()
