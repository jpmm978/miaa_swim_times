from datetime import date
import html
from typing import Optional

from models import Entry, Event, EventType, Result
from timing import format_cs_to_time

SIGNATURE_ROLES = [
    ("referee", "Official 1 Signature & Date"),
    ("starter", "Official 2 Signature & Date"),
    ("home_coach", "Home Coach Signature & Date"),
    ("visitor_coach", "Visitor Coach Signature & Date"),
]


def _normalize_lineup_lookup(
    lineups: dict,
) -> dict[tuple[int, int, int], dict]:
    """Normalizes lineups keyed by either (ev, lane) or (ev, heat, lane) into (ev, heat, lane)."""
    normalized: dict[tuple[int, int, int], dict] = {}
    for key, val in lineups.items():
        if len(key) == 3:
            ev_num, heat_num, lane = int(key[0]), int(key[1]), int(key[2])
        else:
            ev_num, lane = int(key[0]), int(key[1])
            heat_num = int(val.get("heat_number") or 1)
        normalized[(ev_num, heat_num, lane)] = {
            **val,
            "event_number": ev_num,
            "heat_number": heat_num,
            "lane": lane,
        }
    return normalized


def _event_has_lineup_or_result(
    event_number: int,
    norm_lineups: dict[tuple[int, int, int], dict],
    entries: Optional[list[Entry]] = None,
    results: Optional[list[Result]] = None,
) -> bool:
    """Returns True if an event has at least one seeded swimmer/relay or recorded entry/result."""
    has_lineup = any(
        ev_num == event_number and bool(data.get("athlete_ids"))
        for (ev_num, _heat_num, _lane), data in norm_lineups.items()
    )
    if has_lineup:
        return True

    ev_entry_ids = {
        e.entry_id for e in (entries or []) if e.event_number == event_number
    }
    if ev_entry_ids:
        return True

    res_entry_ids = {r.entry_id for r in (results or [])}
    return bool(ev_entry_ids & res_entry_ids)


def _format_lineup_participant(event: Optional[Event], data: Optional[dict]) -> tuple[str, str, str]:
    """Returns (team_str, participant_str, note_str) for a normalized lineup slot."""
    if not data or not data.get("athlete_ids"):
        default_note = "EXH" if (data and (data.get("is_exhibition") or int(data.get("heat_number") or 1) > 1)) else ""
        return ("—", "—", default_note)

    team_str = str(data.get("team_id") or "—")
    athlete_ids = [str(a) for a in (data.get("athlete_ids") or [])]
    relay_letter = data.get("relay_letter")

    if event is not None and event.event_type == EventType.RELAY and relay_letter:
        participant = f"Rly {relay_letter}: {', '.join(athlete_ids)}"
    else:
        participant = ", ".join(athlete_ids)

    heat_num = int(data.get("heat_number") or 1)
    is_exh = bool(data.get("is_exhibition")) or (heat_num > 1)
    note_str = "EXH" if is_exh else ""
    return (team_str, participant, note_str)


def _render_signatures_section(signatures: Optional[dict[str, dict]]) -> str:
    """Renders saved electronic signatures above signature lines, or the default 2-line block."""
    sigs = signatures or {}
    has_any_saved = any(
        str((sigs.get(rk) or {}).get("signature_data_url") or "").strip().startswith("data:image/")
        for rk, _ in SIGNATURE_ROLES
    )

    if not has_any_saved:
        return """
  <section class="signatures">
    <div class="sig-line">Official 1 Signature &amp; Date</div>
    <div class="sig-line">Official 2 Signature &amp; Date</div>
  </section>
"""

    cards: list[str] = []
    for rk, label in SIGNATURE_ROLES:
        rec = sigs.get(rk) or {}
        data_url = str(rec.get("signature_data_url") or "").strip()
        signer_name = str(rec.get("signer_name") or "").strip()
        signed_at = str(rec.get("signed_at") or "").strip()

        if data_url.startswith("data:image/"):
            img_markup = (
                f'<img src="{html.escape(data_url)}" alt="{html.escape(label)}" class="sig-img" />'
            )
            meta_parts = [p for p in (signer_name, signed_at) if p]
            meta_suffix = f" ({html.escape(' · '.join(meta_parts))})" if meta_parts else ""
        else:
            img_markup = '<div class="sig-spacer"></div>'
            meta_suffix = ""

        cards.append(
            f"""
    <div class="sig-card">
      {img_markup}
      <div class="sig-line">{html.escape(label)}{meta_suffix}</div>
    </div>
            """
        )

    return f"""
  <section class="signatures sig-grid-4">
    {''.join(cards)}
  </section>
"""


def export_meet_html(
    team_a: str,
    team_b: str,
    div_totals: dict[str, dict[str, float]],
    events: list[Event],
    entries: list[Entry],
    results: list[Result],
    gender: str = "F",
    meet_date: date | None = None,
    signatures: Optional[dict[str, dict]] = None,
) -> str:
    """Generates a single-page, print-ready HTML meet summary report for one division ('F' or 'M')."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)
    div_label = "Girls" if gender == "F" else "Boys"

    score_a = f"{div_totals[gender].get(team_a, 0.0):g}"
    score_b = f"{div_totals[gender].get(team_b, 0.0):g}"

    entries_by_id = {e.entry_id: e for e in entries}
    div_events = [ev for ev in events if ev.gender == gender]

    event_sections: list[str] = []
    for ev in div_events:
        ev_results = [
            r
            for r in results
            if r.entry_id in entries_by_id
            and entries_by_id[r.entry_id].event_number == ev.event_number
        ]
        if not ev_results:
            continue

        ev_results.sort(
            key=lambda r: (
                getattr(entries_by_id[r.entry_id], "heat_number", 1),
                r.place is None,
                r.place or 999,
            )
        )

        row_html: list[str] = []
        for res in ev_results:
            ent = entries_by_id[res.entry_id]
            heat_num = getattr(ent, "heat_number", 1)
            is_exh = bool(ent.is_exhibition) or (heat_num > 1)

            if ev.event_type == EventType.DIVING:
                perf = f"{res.diving_score:.2f}" if res.diving_score is not None else "—"
            else:
                perf = format_cs_to_time(res.official_time_cs) if res.official_time_cs is not None else "—"

            if ev.event_type == EventType.RELAY and ent.relay_letter:
                participant = f"Rly {ent.relay_letter}: {', '.join(ent.athlete_ids)}"
            else:
                participant = ", ".join(ent.athlete_ids)

            if res.place is not None:
                place_str = f"{res.place}*" if res.manual_place is not None else str(res.place)
            else:
                place_str = "—"

            notes: list[str] = []
            if heat_num > 1:
                notes.append(f"H{heat_num}")
            if res.status.value != "OK":
                notes.append(res.status.value)
            if is_exh:
                notes.append("EXH")
            if res.manual_place is not None:
                notes.append("JD")
            if res.override_note:
                notes.append(res.override_note)
            note_suffix = f" [{', '.join(notes)}]" if notes else ""

            pts_str = f"{res.points:g}" if res.points > 0 else "—"

            row_html.append(
                f"<tr>"
                f"<td class='num'>{place_str}</td>"
                f"<td class='team'>{html.escape(ent.team_id)}</td>"
                f"<td class='name'>{html.escape(participant)}{html.escape(note_suffix)}</td>"
                f"<td class='num'>{html.escape(perf)}</td>"
                f"<td class='num'>{pts_str}</td>"
                f"</tr>"
            )

        event_sections.append(
            f"""
            <section class="event-block">
              <h3>Ev {ev.event_number}: {html.escape(ev.name)}</h3>
              <table>
                <thead>
                  <tr>
                    <th class="num" style="width: 7%;">Pl</th>
                    <th style="width: 21%;">Team</th>
                    <th style="width: 47%;">Participant</th>
                    <th class="num" style="width: 16%;">Official</th>
                    <th class="num" style="width: 9%;">Pts</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(row_html)}
                </tbody>
              </table>
            </section>
            """
        )

    events_markup = "\n".join(event_sections) or f"<p>No {div_label.lower()} event results recorded.</p>"
    signatures_markup = _render_signatures_section(signatures)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{div_label} Meet Results — {esc_a} vs {esc_b}</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.4in;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111;
      max-width: 820px;
      margin: 12px auto;
      padding: 0 12px;
      font-size: 9.5px;
      line-height: 1.22;
    }}
    header {{
      border-bottom: 1.5px solid #222;
      padding-bottom: 4px;
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    header h1 {{
      margin: 0;
      font-size: 15px;
    }}
    .meta {{
      color: #444;
      font-size: 9.5px;
    }}
    .score-banner {{
      display: flex;
      gap: 16px;
      align-items: center;
      background: #f5f5f5;
      border: 1px solid #ccc;
      border-radius: 3px;
      padding: 3px 9px;
      font-size: 11px;
    }}
    .score-banner strong {{
      font-size: 13px;
    }}
    /* Multi-column masonry layout eliminates vertical white-space gaps between uneven events */
    .events-grid {{
      column-count: 2;
      column-gap: 12px;
    }}
    .event-block {{
      display: inline-block;
      width: 100%;
      margin: 0 0 4px 0;
      page-break-inside: avoid;
      break-inside: avoid;
      vertical-align: top;
    }}
    .event-block h3 {{
      margin: 0;
      font-size: 10.5px;
      line-height: 1.25;
      background: #e2e8f0;
      padding: 2px 5px;
      border-left: 3px solid #0f766e;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border-bottom: 1px solid #e2e8f0;
      padding: 1.5px 3.5px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      font-size: 8.5px;
      text-transform: uppercase;
      color: #475569;
      background: #f8fafc;
      border-bottom: 1px solid #94a3b8;
    }}
    tbody tr:nth-child(odd) {{
      background-color: #ffffff;
    }}
    tbody tr:nth-child(even) {{
      background-color: #f4f6f9;
    }}
    .num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .team {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 72px;
    }}
    .name {{
      word-break: break-word;
    }}
    .signatures {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px 28px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .sig-grid-4 {{
      gap: 8px 24px;
    }}
    .sig-card {{
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
    }}
    .sig-img {{
      max-height: 30px;
      max-width: 185px;
      object-fit: contain;
      display: block;
      margin-bottom: 2px;
    }}
    .sig-spacer {{
      height: 26px;
    }}
    .sig-line {{
      border-top: 1px solid #222;
      padding-top: 2px;
      font-size: 9.5px;
      color: #333;
    }}
    .footnote {{
      margin-top: 6px;
      font-size: 8px;
      color: #555;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    @media print {{
      body {{ margin: 0; padding: 0.06in; max-width: 100%; }}
      .score-banner, .event-block h3, th, tbody tr:nth-child(even) {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>High School {div_label} Dual Meet Official Results</h1>
      <div class="meta">{esc_a} vs. {esc_b} &nbsp;|&nbsp; {date_display}</div>
    </div>
    <div class="score-banner">
      <span>{esc_a}: <strong>{score_a}</strong></span>
      <span>|</span>
      <span>{esc_b}: <strong>{score_b}</strong></span>
    </div>
  </header>

  <main class="events-grid">
    {events_markup}
  </main>

  {signatures_markup}
  <div class="footnote">* Indicates Judge's Decision (JD) place override.</div>
</body>
</html>
"""


def export_heat_sheet_html(
    team_a: str,
    team_b: str,
    events: list[Event],
    lineups: dict,
    meet_date: date | None = None,
) -> str:
    """Generates a self-contained, print-ready HTML heat sheet supporting multiple heats per event."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)
    norm_lineups = _normalize_lineup_lookup(lineups)

    event_sections: list[str] = []
    for ev in events:
        if ev.event_type == EventType.DIVING:
            continue

        ev_heats = sorted(
            {
                heat_num
                for (ev_num, heat_num, _lane), data in norm_lineups.items()
                if ev_num == ev.event_number and data.get("athlete_ids")
            }
        )
        if not ev_heats:
            continue

        gender_label = "Girls" if ev.gender == "F" else "Boys"

        for heat_num in ev_heats:
            heat_tag = (
                f"Heat {heat_num} of {len(ev_heats)} (Scoring)"
                if heat_num == 1
                else f"Heat {heat_num} of {len(ev_heats)} (Exhibition)"
            )
            row_html: list[str] = []

            for lane in range(1, 7):
                data = norm_lineups.get((ev.event_number, heat_num, lane))
                if data and data.get("athlete_ids"):
                    team_str = html.escape(data["team_id"])
                    athlete_ids = data["athlete_ids"]
                    relay_letter = data.get("relay_letter")
                    if ev.event_type == EventType.RELAY and relay_letter:
                        participant = f"Relay {relay_letter} ({', '.join(athlete_ids)})"
                    else:
                        participant = ", ".join(athlete_ids)
                    participant_str = html.escape(participant)
                    exh_str = "EXH" if (data.get("is_exhibition") or heat_num > 1) else ""
                else:
                    team_str = "—"
                    participant_str = "—"
                    exh_str = ""

                row_html.append(
                    f"<tr>"
                    f"<td class='center'><strong>{lane}</strong></td>"
                    f"<td>{team_str}</td>"
                    f"<td>{participant_str}</td>"
                    f"<td class='center'>{exh_str}</td>"
                    f"<td class='write-in'></td>"
                    f"</tr>"
                )

            event_sections.append(
                f"""
                <section class="event-block">
                  <h3>Event {ev.event_number}: {gender_label} {html.escape(ev.name)} — {html.escape(heat_tag)}</h3>
                  <table>
                    <thead>
                      <tr>
                        <th class="center" style="width: 8%;">Lane</th>
                        <th style="width: 22%;">Team</th>
                        <th style="width: 44%;">Swimmer(s)</th>
                        <th class="center" style="width: 8%;">Note</th>
                        <th style="width: 18%;">Time / Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {''.join(row_html)}
                    </tbody>
                  </table>
                </section>
                """
            )

    events_markup = "\n".join(event_sections) or "<p>No lineups saved yet.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Heat Sheet — {esc_a} vs {esc_b}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111;
      max-width: 850px;
      margin: 24px auto;
      padding: 0 16px;
      font-size: 13px;
      line-height: 1.4;
    }}
    header {{
      border-bottom: 2px solid #222;
      padding-bottom: 10px;
      margin-bottom: 18px;
      display: flex;
      justify-content: space-between;
      align-items: baseline;
    }}
    header h1 {{
      margin: 0;
      font-size: 20px;
    }}
    .meta {{
      color: #444;
      font-size: 12px;
    }}
    .event-block {{
      margin-bottom: 18px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .event-block h3 {{
      margin: 0 0 6px 0;
      font-size: 14px;
      background: #e2e8f0;
      padding: 4px 8px;
      border-left: 4px solid #0f766e;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border-bottom: 1px solid #ddd;
      padding: 5px 6px;
      text-align: left;
    }}
    th {{
      font-size: 11px;
      text-transform: uppercase;
      color: #475569;
      background: #f8fafc;
      border-bottom: 1px solid #94a3b8;
    }}
    tbody tr:nth-child(odd) {{
      background-color: #ffffff;
    }}
    tbody tr:nth-child(even) {{
      background-color: #f4f6f9;
    }}
    .center {{ text-align: center; }}
    .write-in {{ border-left: 1px solid #ddd; }}
    @media print {{
      body {{ margin: 0; max-width: 100%; }}
      .event-block h3, th, tbody tr:nth-child(even) {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>MIAA Dual Meet Heat Sheet</h1>
      <div class="meta">{esc_a} (Even Lanes) vs. {esc_b} (Odd Lanes)</div>
    </div>
    <div class="meta">{date_display}</div>
  </header>

  {events_markup}
</body>
</html>
"""


def export_lane_timer_sheets_html(
    team_a: str,
    team_b: str,
    events: list[Event],
    lineups: dict,
    meet_date: date | None = None,
) -> str:
    """Generates a 6-page print-ready HTML packet (one timer sheet per lane, with rows for every heat)."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)
    norm_lineups = _normalize_lineup_lookup(lineups)

    lane_pages: list[str] = []
    for lane in range(1, 7):
        default_side = f"{esc_a} (Home)" if lane % 2 == 0 else f"{esc_b} (Visitor)"
        row_html: list[str] = []

        for ev in events:
            gender_label = "Girls" if ev.gender == "F" else "Boys"
            ev_label = f"{gender_label} {html.escape(ev.name)}"

            if ev.event_type == EventType.DIVING:
                row_html.append(
                    f"<tr class='diving-row'>"
                    f"<td class='center'><strong>{ev.event_number}</strong></td>"
                    f"<td class='center'>—</td>"
                    f"<td>{ev_label}</td>"
                    f"<td colspan='5' class='center'><em>Diving Break — No Lane Timing</em></td>"
                    f"</tr>"
                )
                continue

            ev_heats = sorted(
                {
                    heat_num
                    for (ev_num, heat_num, _l), data in norm_lineups.items()
                    if ev_num == ev.event_number and data.get("athlete_ids")
                }
            )
            if not ev_heats:
                ev_heats = [1]

            for heat_num in ev_heats:
                data = norm_lineups.get((ev.event_number, heat_num, lane))
                if data and data.get("athlete_ids"):
                    athlete_ids = data["athlete_ids"]
                    relay_letter = data.get("relay_letter")
                    if ev.event_type == EventType.RELAY and relay_letter:
                        participant = f"Relay {relay_letter}: {', '.join(athlete_ids)}"
                    else:
                        participant = ", ".join(athlete_ids)
                    swimmer_str = html.escape(participant)
                    note_str = "EXH" if (data.get("is_exhibition") or heat_num > 1) else ""
                else:
                    swimmer_str = ""
                    note_str = "EXH" if heat_num > 1 else ""

                row_html.append(
                    f"<tr>"
                    f"<td class='center'><strong>{ev.event_number}</strong></td>"
                    f"<td class='center'>H{heat_num}</td>"
                    f"<td>{ev_label}</td>"
                    f"<td class='swimmer'>{swimmer_str}</td>"
                    f"<td class='watch'></td>"
                    f"<td class='watch'></td>"
                    f"<td class='watch'></td>"
                    f"<td class='center note'>{note_str}</td>"
                    f"</tr>"
                )

        page_class = "lane-page" if lane < 6 else "lane-page last-page"
        lane_pages.append(
            f"""
            <section class="{page_class}">
              <header>
                <div>
                  <h1>LANE {lane} — TIMER SHEET</h1>
                  <div class="meta">{esc_a} vs. {esc_b} &nbsp;|&nbsp; Default Lane: {default_side}</div>
                </div>
                <div class="meta right">
                  <div>{date_display}</div>
                  <div class="timer-line">Timer(s): __________________________</div>
                </div>
              </header>
              <table>
                <thead>
                  <tr>
                    <th class="center" style="width: 5%;">Ev</th>
                    <th class="center" style="width: 5%;">Ht</th>
                    <th style="width: 23%;">Event</th>
                    <th style="width: 30%;">Swimmer / Relay</th>
                    <th class="center" style="width: 10%;">Watch 1</th>
                    <th class="center" style="width: 10%;">Watch 2</th>
                    <th class="center" style="width: 10%;">Watch 3</th>
                    <th class="center" style="width: 7%;">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(row_html)}
                </tbody>
              </table>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Lane Timer Sheets — {esc_a} vs {esc_b}</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.4in;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111;
      margin: 0;
      padding: 16px;
      font-size: 11px;
      line-height: 1.25;
    }}
    .lane-page {{
      max-width: 820px;
      margin: 0 auto 32px auto;
      page-break-after: always;
      break-after: page;
    }}
    .lane-page.last-page {{
      page-break-after: auto;
      break-after: auto;
    }}
    header {{
      border-bottom: 2px solid #222;
      padding-bottom: 6px;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
    }}
    header h1 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.03em;
    }}
    .meta {{
      color: #333;
      font-size: 11px;
    }}
    .right {{
      text-align: right;
    }}
    .timer-line {{
      margin-top: 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border: 1px solid #999;
      padding: 4px 5px;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      font-size: 10px;
      text-transform: uppercase;
      background: #e2e8f0;
      color: #1e293b;
    }}
    tbody tr:nth-child(odd) {{
      background-color: #ffffff;
    }}
    tbody tr:nth-child(even) {{
      background-color: #f4f6f9;
    }}
    td.swimmer {{
      font-size: 10.5px;
    }}
    td.watch {{
      height: 19px;
    }}
    tr.diving-row td {{
      background-color: #e9edf2;
      color: #475569;
      padding: 3px 5px;
    }}
    .center {{ text-align: center; }}
    @media print {{
      body {{ padding: 0; }}
      .lane-page {{ max-width: 100%; margin: 0; }}
      th, tbody tr:nth-child(even), tr.diving-row td {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  {''.join(lane_pages)}
</body>
</html>
"""


def export_event_pair_timer_sheets_html(
    team_a: str,
    team_b: str,
    events: list[Event],
    lineups: dict,
    meet_date: date | None = None,
    only_populated: bool = False,
    entries: Optional[list[Entry]] = None,
    results: Optional[list[Result]] = None,
) -> str:
    """Generates a print-ready HTML packet pairing Girls & Boys events per page.

    When `only_populated=True`, skips empty events that have no saved lineups,
    entries, or results, and omits pages with no active events.
    """
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)
    norm_lineups = _normalize_lineup_lookup(lineups)

    event_pairs = [events[i : i + 2] for i in range(0, len(events), 2)]
    pages_html: list[str] = []

    for pair in event_pairs:
        active_pair = [
            ev
            for ev in pair
            if not only_populated
            or _event_has_lineup_or_result(ev.event_number, norm_lineups, entries, results)
        ]
        if not active_pair:
            continue

        pair_title = " &amp; ".join(
            f"Ev {ev.event_number} ({'Girls' if ev.gender == 'F' else 'Boys'})"
            for ev in active_pair
        )
        base_name = html.escape(active_pair[0].name)
        blocks_html: list[str] = []

        for ev in active_pair:
            g_label = "Girls" if ev.gender == "F" else "Boys"
            ev_heading = f"Event {ev.event_number}: {g_label} {html.escape(ev.name)}"

            if ev.event_type == EventType.DIVING:
                blocks_html.append(
                    f"""
                    <div class="ev-card">
                      <div class="ev-bar">
                        <span>{ev_heading}</span>
                        <span class="judge-line">Referee / Judge: ______________________</span>
                      </div>
                      <table>
                        <thead>
                          <tr>
                            <th class="center" style="width: 8%;">Ord</th>
                            <th style="width: 24%;">Team</th>
                            <th style="width: 42%;">Diver Name</th>
                            <th class="center" style="width: 16%;">Total Score</th>
                            <th class="center" style="width: 10%;">Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(
                              f"<tr><td class='center'><strong>{slot}</strong></td><td></td><td></td><td class='watch'></td><td></td></tr>"
                              for slot in range(1, 7)
                          )}
                        </tbody>
                      </table>
                    </div>
                    """
                )
                continue

            ev_heats = sorted(
                {
                    heat_num
                    for (ev_num, heat_num, _lane), data in norm_lineups.items()
                    if ev_num == ev.event_number and data.get("athlete_ids")
                }
            )
            if not ev_heats:
                ev_heats = [1]

            for heat_num in ev_heats:
                heat_suffix = (
                    f" — Heat {heat_num} (Scoring)"
                    if heat_num == 1
                    else f" — Heat {heat_num} (Exhibition)"
                )
                rows_html: list[str] = []

                for lane in range(1, 7):
                    default_team = team_a if lane % 2 == 0 else team_b
                    data = norm_lineups.get((ev.event_number, heat_num, lane))
                    if data and data.get("athlete_ids"):
                        t_str = html.escape(data.get("team_id") or default_team)
                        athlete_ids = data["athlete_ids"]
                        relay_letter = data.get("relay_letter")
                        if ev.event_type == EventType.RELAY and relay_letter:
                            participant = f"Rly {relay_letter}: {', '.join(athlete_ids)}"
                        else:
                            participant = ", ".join(athlete_ids)
                        swimmer_str = html.escape(participant)
                        note_str = "EXH" if (data.get("is_exhibition") or heat_num > 1) else ""
                    else:
                        t_str = html.escape(default_team)
                        swimmer_str = ""
                        note_str = "EXH" if heat_num > 1 else ""

                    rows_html.append(
                        f"<tr>"
                        f"<td class='center'><strong>{lane}</strong></td>"
                        f"<td>{t_str}</td>"
                        f"<td class='swimmer'>{swimmer_str}</td>"
                        f"<td class='watch'></td>"
                        f"<td class='watch'></td>"
                        f"<td class='watch'></td>"
                        f"<td class='center'>{note_str}</td>"
                        f"</tr>"
                    )

                blocks_html.append(
                    f"""
                    <div class="ev-card">
                      <div class="ev-bar">
                        <span>{ev_heading}{html.escape(heat_suffix)}</span>
                        <span class="judge-line">Head Timer / Stroke Judge: ______________________</span>
                      </div>
                      <table>
                        <thead>
                          <tr>
                            <th class="center" style="width: 7%;">Lane</th>
                            <th style="width: 20%;">Team</th>
                            <th style="width: 34%;">Swimmer / Relay</th>
                            <th class="center" style="width: 11%;">Watch 1</th>
                            <th class="center" style="width: 11%;">Watch 2</th>
                            <th class="center" style="width: 11%;">Watch 3</th>
                            <th class="center" style="width: 6%;">Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(rows_html)}
                        </tbody>
                      </table>
                    </div>
                    """
                )

        pages_html.append(
            f"""
            <section class="pair-page">
              <header>
                <div>
                  <h1>EVENT TIMER CARD — {base_name}</h1>
                  <div class="meta">{esc_a} (Even Lanes) vs. {esc_b} (Odd Lanes) &nbsp;|&nbsp; {pair_title}</div>
                </div>
                <div class="meta right">{date_display}</div>
              </header>
              {''.join(blocks_html)}
            </section>
            """
        )

    if pages_html:
        pages_html[-1] = pages_html[-1].replace(
            '<section class="pair-page">', '<section class="pair-page last-page">', 1
        )

    body_content = (
        "".join(pages_html)
        if pages_html
        else "<p>No events with saved lineups or recorded results found.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Event Timer Cards (Girls &amp; Boys Paired) — {esc_a} vs {esc_b}</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.4in;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111;
      margin: 0;
      padding: 16px;
      font-size: 11px;
      line-height: 1.25;
    }}
    .pair-page {{
      max-width: 820px;
      margin: 0 auto 32px auto;
      page-break-after: always;
      break-after: page;
    }}
    .pair-page.last-page {{
      page-break-after: auto;
      break-after: auto;
    }}
    header {{
      border-bottom: 2px solid #222;
      padding-bottom: 6px;
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
    }}
    header h1 {{
      margin: 0;
      font-size: 17px;
      letter-spacing: 0.02em;
    }}
    .meta {{
      color: #333;
      font-size: 11px;
    }}
    .right {{
      text-align: right;
    }}
    .ev-card {{
      margin-bottom: 16px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .ev-bar {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      font-weight: 700;
      font-size: 12px;
      background: #e2e8f0;
      padding: 5px 8px;
      border-left: 4px solid #0f766e;
      border-top: 1px solid #94a3b8;
      border-right: 1px solid #94a3b8;
    }}
    .judge-line {{
      font-weight: 400;
      font-size: 10px;
      color: #334155;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border: 1px solid #999;
      padding: 5px 6px;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      font-size: 10px;
      text-transform: uppercase;
      background: #f8fafc;
      color: #1e293b;
    }}
    tbody tr:nth-child(odd) {{
      background-color: #ffffff;
    }}
    tbody tr:nth-child(even) {{
      background-color: #f4f6f9;
    }}
    td.swimmer {{
      font-size: 11px;
    }}
    td.watch {{
      height: 22px;
    }}
    .center {{ text-align: center; }}
    @media print {{
      body {{ padding: 0; }}
      .pair-page {{ max-width: 100%; margin: 0; }}
      .ev-bar, th, tbody tr:nth-child(even) {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  {body_content}
</body>
</html>
"""


def export_lane_event_pair_sheets_html(
    team_a: str,
    team_b: str,
    events: list[Event],
    lineups: dict,
    meet_date: date | None = None,
    only_populated: bool = False,
    entries: Optional[list[Entry]] = None,
    results: Optional[list[Result]] = None,
) -> str:
    """Generates a print-ready HTML packet with one page per lane for each event pair.

    Page ordering:
- Events 1 & 2: Lane 1, Lane 2, ..., Lane 6
- Events 3 & 4: Lane 1, Lane 2, ..., Lane 6
- ... through Events 23 & 24: Lane 1, Lane 2, ..., Lane 6
    """
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)
    norm_lineups = _normalize_lineup_lookup(lineups)
    events_by_num = {ev.event_number: ev for ev in events}

    max_ev = max([24] + list(events_by_num.keys()))
    if max_ev % 2 == 1:
        max_ev += 1

    pages_html: list[str] = []

    for ev_a in range(1, max_ev + 1, 2):
        ev_b = ev_a + 1
        pair_ev_nums = [n for n in (ev_a, ev_b) if n in events_by_num or n <= 24]
        if not pair_ev_nums:
            continue

        if only_populated and not any(
            _event_has_lineup_or_result(n, norm_lineups, entries, results)
            for n in (ev_a, ev_b)
        ):
            continue

        for lane in range(1, 7):
            default_side = f"{esc_a} (Even)" if lane % 2 == 0 else f"{esc_b} (Odd)"
            event_blocks: list[str] = []

            for ev_num in (ev_a, ev_b):
                ev = events_by_num.get(ev_num)
                if ev is not None:
                    g_label = "Girls" if ev.gender == "F" else "Boys"
                    ev_heading = f"Event {ev.event_number}: {g_label} {html.escape(ev.name)}"
                else:
                    ev_heading = f"Event {ev_num}"

                if ev is not None and ev.event_type == EventType.DIVING:
                    event_blocks.append(
                        f"""
                        <div class="ev-card">
                          <div class="ev-bar">
                            <span>{ev_heading}</span>
                            <span class="lane-tag">Lane {lane} — Diving</span>
                          </div>
                          <table>
                            <thead>
                              <tr>
                                <th class="center" style="width: 10%;">Heat</th>
                                <th style="width: 22%;">Team</th>
                                <th style="width: 34%;">Diver</th>
                                <th class="center" style="width: 10%;">Score 1</th>
                                <th class="center" style="width: 10%;">Score 2</th>
                                <th class="center" style="width: 14%;">Total / Note</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr class="diving-row">
                                <td class="center">—</td>
                                <td colspan="5" class="center"><em>Diving Event — No Swim Lane Timing</em></td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                        """
                    )
                    continue

                ev_heats = sorted(
                    {
                        heat_num
                        for (e_num, heat_num, _l), data in norm_lineups.items()
                        if e_num == ev_num and data.get("athlete_ids")
                    }
                )
                if not ev_heats:
                    ev_heats = [1]

                rows_html: list[str] = []
                for heat_num in ev_heats:
                    data = norm_lineups.get((ev_num, heat_num, lane))
                    t_raw, p_raw, n_raw = _format_lineup_participant(ev, data)
                    heat_label = f"H{heat_num}"
                    heat_role = "Scoring" if heat_num == 1 else "EXH"
                    note_combined = " / ".join(x for x in (heat_role, n_raw) if x)

                    rows_html.append(
                        f"<tr>"
                        f"<td class='center'><strong>{heat_label}</strong></td>"
                        f"<td>{html.escape(t_raw)}</td>"
                        f"<td class='swimmer'>{html.escape(p_raw)}</td>"
                        f"<td class='watch'></td>"
                        f"<td class='watch'></td>"
                        f"<td class='watch'></td>"
                        f"<td class='center note'>{html.escape(note_combined)}</td>"
                        f"</tr>"
                    )

                event_blocks.append(
                    f"""
                    <div class="ev-card">
                      <div class="ev-bar">
                        <span>{ev_heading}</span>
                        <span class="lane-tag">Lane {lane}</span>
                      </div>
                      <table>
                        <thead>
                          <tr>
                            <th class="center" style="width: 8%;">Heat</th>
                            <th style="width: 18%;">Team</th>
                            <th style="width: 33%;">Swimmer / Relay</th>
                            <th class="center" style="width: 10.5%;">Watch 1</th>
                            <th class="center" style="width: 10.5%;">Watch 2</th>
                            <th class="center" style="width: 10.5%;">Watch 3</th>
                            <th class="center" style="width: 9.5%;">Role / Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(rows_html)}
                        </tbody>
                      </table>
                    </div>
                    """
                )

            pages_html.append(
                f"""
                <section class="lane-pair-page">
                  <header>
                    <div>
                      <h1>LANE {lane} — EVENTS {ev_a} &amp; {ev_b}</h1>
                      <div class="meta">{esc_a} vs. {esc_b} &nbsp;|&nbsp; {default_side} &nbsp;|&nbsp; Heat 1 Scores · Heat 2+ Exhibition</div>
                    </div>
                    <div class="meta right">
                      <div>{date_display}</div>
                      <div class="timer-line">Lane {lane} Timer: ______________________</div>
                    </div>
                  </header>
                  <main>
                    {''.join(event_blocks)}
                  </main>
                  <footer>
                    <span>Events {ev_a} &amp; {ev_b} — Lane {lane}</span>
                    <span>Official Initials: ________________</span>
                  </footer>
                </section>
                """
            )

    if pages_html:
        pages_html[-1] = pages_html[-1].replace(
            '<section class="lane-pair-page">',
            '<section class="lane-pair-page last-page">',
            1,
        )

    body_content = (
        "".join(pages_html)
        if pages_html
        else "<p>No populated event-pair lane sheets found for the selected filter.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Lane Event-Pair Timer Sheets — {esc_a} vs {esc_b}</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.4in;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #111;
      margin: 0;
      padding: 16px;
      font-size: 11px;
      line-height: 1.25;
    }}
    .lane-pair-page {{
      max-width: 820px;
      margin: 0 auto 32px auto;
      page-break-after: always;
      break-after: page;
    }}
    .lane-pair-page.last-page {{
      page-break-after: auto;
      break-after: auto;
    }}
    header {{
      border-bottom: 2px solid #222;
      padding-bottom: 6px;
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
    }}
    header h1 {{
      margin: 0;
      font-size: 17px;
      letter-spacing: 0.02em;
    }}
    .meta {{
      color: #333;
      font-size: 10.5px;
    }}
    .right {{
      text-align: right;
    }}
    .timer-line {{
      margin-top: 3px;
    }}
    .ev-card {{
      margin-bottom: 16px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .ev-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: 700;
      font-size: 12px;
      background: #e2e8f0;
      padding: 5px 8px;
      border-left: 4px solid #0f766e;
      border-top: 1px solid #94a3b8;
      border-right: 1px solid #94a3b8;
    }}
    .lane-tag {{
      font-size: 10.5px;
      background: #ffffff;
      color: #0f172a;
      border: 1px solid #94a3b8;
      border-radius: 3px;
      padding: 1px 7px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border: 1px solid #999;
      padding: 5px 6px;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      font-size: 10px;
      text-transform: uppercase;
      background: #f8fafc;
      color: #1e293b;
    }}
    tbody tr:nth-child(odd) {{
      background-color: #ffffff;
    }}
    tbody tr:nth-child(even) {{
      background-color: #f4f6f9;
    }}
    td.swimmer {{
      font-size: 11px;
    }}
    td.watch {{
      height: 22px;
    }}
    td.note {{
      font-size: 9.5px;
      font-weight: 600;
    }}
    tr.diving-row td {{
      background-color: #e9edf2;
      color: #475569;
    }}
    footer {{
      margin-top: 12px;
      padding-top: 6px;
      border-top: 1px solid #cbd5e1;
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      color: #334155;
    }}
    .center {{ text-align: center; }}
    @media print {{
      body {{ padding: 0; }}
      .lane-pair-page {{ max-width: 100%; margin: 0; }}
      .ev-bar, .lane-tag, th, tbody tr:nth-child(even), tr.diving-row td {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  {body_content}
</body>
</html>
"""
