import csv
import io
import json
import sqlite3
from pathlib import Path

from models import Entry, Event, EventType, Result, ResultStatus
from timing import format_cs_to_time

DB_PATH = Path("swim_meet.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Creates tables if they do not already exist."""
    with _get_conn() as conn:
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
                event_number INTEGER NOT NULL,
                team_id TEXT NOT NULL,
                athlete_ids TEXT NOT NULL,
                is_exhibition INTEGER NOT NULL,
                relay_letter TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                entry_id TEXT PRIMARY KEY,
                pad_time_cs INTEGER,
                backup_times_cs TEXT NOT NULL,
                diving_score REAL,
                status TEXT NOT NULL,
                official_time_cs INTEGER,
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
            "INSERT OR IGNORE INTO meet_meta (key, value) VALUES ('team_a', 'Home Team')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO meet_meta (key, value) VALUES ('team_b', 'Visiting Team')"
        )


def load_team_names() -> tuple[str, str]:
    with _get_conn() as conn:
        rows = dict(conn.execute("SELECT key, value FROM meet_meta").fetchall())
    return rows.get("team_a", "Home Team"), rows.get("team_b", "Visiting Team")


def save_team_names(team_
