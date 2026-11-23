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


def save_team_names(team_a: str, team_b: str) -> None:
    old_a, old_b = load_team_names()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_a', ?)", (team_a,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO meet_meta (key, value) VALUES ('team_b', ?)", (team_b,)
        )
        if old_a != team_a:
            conn.execute("UPDATE roster SET team_id = ? WHERE team_id = ?", (team_a, old_a))
        if old_b != team_b:
            conn.execute("UPDATE roster SET team_id = ? WHERE team_id = ?", (team_b, old_b))


def save_entry_and_result(entry: Entry, result: Result) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO entries (entry_id, event_number, team_id, athlete_ids, is_exhibition, relay_letter)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.entry_id,
                entry.event_number,
                entry.team_id,
                json.dumps(entry.athlete_ids),
                int(entry.is_exhibition),
                entry.relay_letter,
            ),
        )
        conn.execute(
            """
            INSERT INTO results (entry_id, pad_time_cs, backup_times_cs, diving_score, status, official_time_cs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.entry_id,
                result.pad_time_cs,
                json.dumps(result.backup_times_cs),
                result.diving_score,
                result.status.value,
                result.official_time_cs,
            ),
        )


def load_all_data() -> tuple[list[Entry], list[Result]]:
    with _get_conn() as conn:
        entry_rows = conn.execute("SELECT * FROM entries").fetchall()
        result_rows = conn.execute("SELECT * FROM results").fetchall()

    entries = [
        Entry(
            entry_id=r["entry_id"],
            event_number=r["event_number"],
            team_id=r["team_id"],
            athlete_ids=json.loads(r["athlete_ids"]),
            is_exhibition=bool(r["is_exhibition"]),
            relay_letter=r["relay_letter"],
        )
        for r in entry_rows
    ]
    results = [
        Result(
            entry_id=r["entry_id"],
            pad_time_cs=r["pad_time_cs"],
            backup_times_cs=json.loads(r["backup_times_cs"]),
            diving_score=r["diving_score"],
            status=ResultStatus(r["status"]),
            official_time_cs=r["official_time_cs"],
        )
        for r in result_rows
    ]
    return entries, results


def clear_event(event_number: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM results WHERE entry_id IN (SELECT entry_id FROM entries WHERE event_number = ?)",
            (event_number,),
        )
        conn.execute("DELETE FROM entries WHERE event_number = ?", (event_number,))


def clear_all() -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM results")
        conn.execute("DELETE FROM entries")


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

        # Skip header row if present
        if idx == 0 and cells[0].lower() in ("name", "swimmer", "athlete", "last", "last name"):
            continue

        # Last cell is gender; everything before it is the swimmer's name
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
            perf = format_cs_to_time(res.official_time_cs) if res.official_time_cs is not None else ""

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
