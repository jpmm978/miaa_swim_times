from datetime import date
import re

from models import Entry, Event, EventType, Result, ResultStatus
from timing import format_cs_to_time

ORG_HIGH_SCHOOL = "8"  # SDIF Org Code 8 = High School / NFHS


def _new_line() -> list[str]:
    return [" "] * 160


def _put(buf: list[str], col: int, length: int, text: str, right: bool = False) -> None:
    """Places text into a 1-based SDIF column slice, padded to exact length."""
    cleaned = str(text)[:length]
    padded = cleaned.rjust(length) if right else cleaned.ljust(length)
    buf[col - 1 : col - 1 + length] = list(padded)


def _make_team_code(team_name: str, fallback_idx: int) -> str:
    """Builds a 6-character alphanumeric SDIF team code (e.g., 'MAHOME')."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", team_name).upper()
    prefix = (alnum[:4] or f"TM{fallback_idx:02d}").ljust(4, "X")
    return f"MA{prefix}"[:6]


def _parse_distance_and_stroke(event: Event) -> tuple[int, str]:
    """Maps event name/type to SDIF distance and stroke code (1-7)."""
    match = re.match(r"(\d+)", event.name)
    distance = int(match.group(1)) if match else 0
    lower = event.name.lower()

    if event.event_type == EventType.RELAY:
        return distance, ("7" if "medley" in lower else "6")
    if "back" in lower:
        return distance, "2"
    if "breast" in lower:
        return distance, "3"
    if "fly" in lower or "butter" in lower:
        return distance, "4"
    if "medley" in lower or "im" in lower:
        return distance, "5"
    return distance, "1"  # Freestyle default


def _format_sdif_time(result: Result) -> str:
    """Formats official time or status code into an 8-char SDIF time field."""
    if result.status in (ResultStatus.DQ, ResultStatus.NS, ResultStatus.DFS, ResultStatus.DNF):
        return result.status.value.ljust(8)
    if result.official_time_cs is None:
        return "NT".ljust(8)
    return format_cs_to_time(result.official_time_cs).rjust(8)


def _is_exhibition_entry(entry: Entry) -> bool:
    """Any Heat 2+ entry or explicitly flagged exhibition entry is exhibition."""
    return bool(entry.is_exhibition) or (int(getattr(entry, "heat_number", 1) or 1) > 1)


def export_meet_sd3(
    meet_name: str,
    events: list[Event],
    entries: list[Entry],
    results: list[Result],
    meet_date: date | None = None,
    state: str = "MA",
) -> str:
    """Generates a Hy-Tek Team Manager-compatible SDIF (.sd3) string."""
    today = meet_date or date.today()
    date_str = today.strftime("%m%d%Y")

    events_by_num = {e.event_number: e for e in events}
    results_by_entry = {r.entry_id: r for r in results}

    unique_teams = sorted({e.team_id for e in entries})
    team_codes = {name: _make_team_code(name, idx + 1) for idx, name in enumerate(unique_teams)}

    lines: list[str] = []
    d_count = 0
    e_count = 0
    f_count = 0

    # --- A0: File Description Record ---
    a0 = _new_line()
    _put(a0, 1, 2, "A0")
    _put(a0, 3, 1, ORG_HIGH_SCHOOL)
    _put(a0, 4, 8, "V3")
    _put(a0, 12, 2, "02")  # 02 = Meet Results
    _put(a0, 44, 20, "MIAA Python Scorer")
    _put(a0, 64, 10, "1.0")
    _put(a0, 106, 8, date_str)
    lines.append("".join(a0))

    # --- B1: Meet Record ---
    b1 = _new_line()
    _put(b1, 1, 2, "B1")
    _put(b1, 3, 1, ORG_HIGH_SCHOOL)
    _put(b1, 12, 30, meet_name)
    _put(b1, 106, 2, state)
    _put(b1, 118, 3, "USA")
    _put(b1, 121, 1, "5")  # 5 = Dual Meet
    _put(b1, 122, 8, date_str)
    _put(b1, 130, 8, date_str)
    _put(b1, 150, 1, "Y")  # Y = Short Course Yards (SCY)
    lines.append("".join(b1))

    # --- C1: Team Records ---
    for team_name in unique_teams:
        c1 = _new_line()
        _put(c1, 1, 2, "C1")
        _put(c1, 3, 1, ORG_HIGH_SCHOOL)
        _put(c1, 12, 6, team_codes[team_name])
        _put(c1, 18, 30, team_name)
        _put(c1, 48, 16, team_name)
        _put(c1, 148, 3, "USA")
        lines.append("".join(c1))

    # --- D0 (Individual) and E0/F0 (Relay) Records ---
    for team_name in unique_teams:
        team_entries = [e for e in entries if e.team_id == team_name]
        team_entries.sort(key=lambda e: (e.event_number, int(getattr(e, "heat_number", 1) or 1)))

        for entry in team_entries:
            ev = events_by_num.get(entry.event_number)
            res = results_by_entry.get(entry.entry_id)
            if not ev or not res or ev.event_type == EventType.DIVING:
                continue  # SDIF v3 does not support diving records

            heat_num = int(getattr(entry, "heat_number", 1) or 1)
            is_exh = _is_exhibition_entry(entry)
            distance, stroke_code = _parse_distance_and_stroke(ev)
            time_field = _format_sdif_time(res)
            place_str = "" if is_exh else (str(res.place) if res.place is not None else "")
            pts_str = "" if is_exh else (f"{res.points:.1f}" if res.points > 0 else "")
            heat_str = str(heat_num)

            if ev.event_type == EventType.INDIVIDUAL:
                d0 = _new_line()
                _put(d0, 1, 2, "D0")
                _put(d0, 3, 1, ORG_HIGH_SCHOOL)
                _put(d0, 12, 28, entry.athlete_ids[0])
                _put(d0, 52, 1, "A")  # Attached
                _put(d0, 66, 1, ev.gender)
                _put(d0, 67, 1, ev.gender)
                _put(d0, 68, 4, str(distance), right=True)
                _put(d0, 72, 1, stroke_code)
                _put(d0, 73, 4, str(ev.event_number))
                _put(d0, 77, 4, "UNOV")  # Open / Varsity
                _put(d0, 81, 8, date_str)
                _put(d0, 116, 8, time_field, right=True)
                _put(d0, 124, 1, "Y")
                _put(d0, 125, 2, heat_str, right=True)
                if is_exh:
                    _put(d0, 131, 1, "X")
                _put(d0, 132, 3, place_str, right=True)
                _put(d0, 135, 4, pts_str, right=True)
                lines.append("".join(d0))
                d_count += 1

            elif ev.event_type == EventType.RELAY:
                relay_letter = (entry.relay_letter or "A")[0].upper()
                swimmers = entry.athlete_ids[:4]

                e0 = _new_line()
                _put(e0, 1, 2, "E0")
                _put(e0, 3, 1, ORG_HIGH_SCHOOL)
                _put(e0, 12, 1, relay_letter)
                _put(e0, 13, 6, team_codes[team_name])
                _put(e0, 19, 2, str(len(swimmers)), right=True)
                _put(e0, 21, 1, ev.gender)
                _put(e0, 22, 4, str(distance), right=True)
                _put(e0, 26, 1, stroke_code)
                _put(e0, 27, 4, str(ev.event_number))
                _put(e0, 31, 4, "UNOV")
                _put(e0, 38, 8, date_str)
                _put(e0, 73, 8, time_field, right=True)
                _put(e0, 81, 1, "Y")
                _put(e0, 82, 2, heat_str, right=True)
                if is_exh:
                    _put(e0, 88, 1, "X")
                _put(e0, 89, 3, place_str, right=True)
                _put(e0, 92, 4, pts_str, right=True)
                lines.append("".join(e0))
                e_count += 1

                for leg_idx, swimmer_name in enumerate(swimmers, start=1):
                    f0 = _new_line()
                    _put(f0, 1, 2, "F0")
                    _put(f0, 3, 1, ORG_HIGH_SCHOOL)
                    _put(f0, 16, 6, team_codes[team_name])
                    _put(f0, 22, 1, relay_letter)
                    _put(f0, 23, 28, swimmer_name)
                    _put(f0, 75, 1, ev.gender)
                    _put(f0, 76, 1, "0")  # Prelim order
                    _put(f0, 77, 1, "0")  # Swim-off order
                    _put(f0, 78, 1, str(leg_idx))  # Finals leg order (1-4)
                    lines.append("".join(f0))
                    f_count += 1

    # --- Z0: File Terminator Record ---
    z0 = _new_line()
    _put(z0, 1, 2, "Z0")
    _put(z0, 3, 1, ORG_HIGH_SCHOOL)
    _put(z0, 12, 2, "02")
    _put(z0, 44, 3, "1", right=True)
    _put(z0, 47, 3, "1", right=True)
    _put(z0, 50, 4, str(len(unique_teams)), right=True)
    _put(z0, 54, 4, str(len(unique_teams)), right=True)
    _put(z0, 58, 6, str(d_count), right=True)
    _put(z0, 70, 5, str(e_count), right=True)
    _put(z0, 75, 6, str(f_count), right=True)
    lines.append("".join(z0))

    return "\r\n".join(lines) + "\r\n"
