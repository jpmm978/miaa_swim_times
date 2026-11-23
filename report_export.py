from datetime import date
import html

from models import Entry, Event, EventType, Result
from timing import format_cs_to_time


def export_meet_html(
    team_a: str,
    team_b: str,
    div_totals: dict[str, dict[str, float]],
    events: list[Event],
    entries: list[Entry],
    results: list[Result],
    meet_date: date | None = None,
) -> str:
    """Generates a self-contained, print-ready HTML meet summary report."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)

    girls_a = f"{div_totals['F'].get(team_a, 0.0):g}"
    girls_b = f"{div_totals['F'].get(team_b, 0.0):g}"
    boys_a = f"{div_totals['M'].get(team_a, 0.0):g}"
    boys_b = f"{div_totals['M'].get(team_b, 0.0):g}"

    entries_by_id = {e.entry_id: e for e in entries}

    event_sections: list[str] = []
    for ev in events:
        ev_results = [
            r
            for r in results
            if r.entry_id in entries_by_id
            and entries_by_id[r.entry_id].event_number == ev.event_number
        ]
        if not ev_results:
            continue

        ev_results.sort(key=lambda r: (r.place is None, r.place or 999))
        gender_label = "Girls" if ev.gender == "F" else "Boys"

        row_html: list[str] = []
        for res in ev_results:
            ent = entries_by_id[res.entry_id]
            if ev.event_type == EventType.DIVING:
                perf = f"{res.diving_score:.2f}" if res.diving_score is not None else "—"
            else:
                perf = format_cs_to_time(res.official_time_cs) if res.official_time_cs is not None else "—"

            if ev.event_type == EventType.RELAY and ent.relay_letter:
                participant = f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
            else:
                participant = ", ".join(ent.athlete_ids)

            if res.place is not None:
                place_str = f"{res.place} (JD)" if res.manual_place is not None else str(res.place)
            else:
                place_str = "—"

            notes: list[str] = []
            if res.status.value != "OK":
                notes.append(res.status.value)
            if ent.is_exhibition:
                notes.append("EXH")
            if res.override_note:
                notes.append(res.override_note)
            status_badge = " ".join(notes)

            pts_str = f"{res.points:g}" if res.points > 0 else "—"

            row_html.append(
                f"<tr>"
                f"<td class='num'>{place_str}</td>"
                f"<td>{html.escape(ent.team_id)}</td>"
                f"<td>{html.escape(participant)}</td>"
                f"<td class='num'>{html.escape(perf)}</td>"
                f"<td class='center'>{html.escape(status_badge)}</td>"
                f"<td class='num'>{pts_str}</td>"
                f"</tr>"
            )

        event_sections.append(
            f"""
            <section class="event-block">
              <h3>Event {ev.event_number}: {gender_label} {html.escape(ev.name)}</h3>
              <table>
                <thead>
                  <tr>
                    <th class="num" style="width: 10%;">Place</th>
                    <th style="width: 22%;">Team</th>
                    <th style="width: 36%;">Participant</th>
                    <th class="num" style="width: 14%;">Official</th>
                    <th class="center" style="width: 10%;">Note</th>
                    <th class="num" style="width: 8%;">Pts</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(row_html)}
                </tbody>
              </table>
            </section>
            """
        )

    events_markup = "\n".join(event_sections) or "<p>No event results recorded.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Meet Results — {esc_a} vs {esc_b}</title>
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
    .scoreboard {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .score-card {{
      border: 1px solid #ccc;
      border-radius: 4px;
      padding: 10px 14px;
      background: #fafafa;
    }}
    .score-card h2 {{
      margin: 0 0 8px 0;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #333;
    }}
    .score-row {{
      display: flex;
      justify-content: space-between;
      font-size: 15px;
      padding: 2px 0;
    }}
    .score-val {{
      font-weight: 700;
    }}
    .event-block {{
      margin-bottom: 18px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .event-block h3 {{
      margin: 0 0 6px 0;
      font-size: 14px;
      background: #eee;
      padding: 4px 8px;
      border-left: 4px solid #222;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border-bottom: 1px solid #ddd;
      padding: 4px 6px;
      text-align: left;
    }}
    th {{
      font-size: 11px;
      text-transform: uppercase;
      color: #555;
      border-bottom: 1px solid #999;
    }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .center {{ text-align: center; }}
    .signatures {{
      margin-top: 36px;
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 24px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .sig-line {{
      border-top: 1px solid #222;
      padding-top: 6px;
      font-size: 11px;
      color: #444;
    }}
    @media print {{
      body {{ margin: 0; max-width: 100%; }}
      .score-card {{ background: #fff; }}
      .event-block h3 {{ background: #f2f2f2; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>MIAA Dual Meet Official Results</h1>
      <div class="meta">{esc_a} vs. {esc_b}</div>
    </div>
    <div class="meta">{date_display}</div>
  </header>

  <section class="scoreboard">
    <div class="score-card">
      <h2>Girls Division</h2>
      <div class="score-row"><span>{esc_a}</span><span class="score-val">{girls_a}</span></div>
      <div class="score-row"><span>{esc_b}</span><span class="score-val">{girls_b}</span></div>
    </div>
    <div class="score-card">
      <h2>Boys Division</h2>
      <div class="score-row"><span>{esc_a}</span><span class="score-val">{boys_a}</span></div>
      <div class="score-row"><span>{esc_b}</span><span class="score-val">{boys_b}</span></div>
    </div>
  </section>

  {events_markup}

  <section class="signatures">
    <div class="sig-line">Meet Referee Signature</div>
    <div class="sig-line">{esc_a} Coach Signature</div>
    <div class="sig-line">{esc_b} Coach Signature</div>
  </section>
</body>
</html>
"""


def export_heat_sheet_html(
    team_a: str,
    team_b: str,
    events: list[Event],
    lineups: dict[tuple[int, int], dict],
    meet_date: date | None = None,
) -> str:
    """Generates a self-contained, print-ready HTML heat sheet from saved lineups."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)

    event_sections: list[str] = []
    for ev in events:
        if ev.event_type == EventType.DIVING:
            continue

        ev_lanes = {
            lane: lineups[(ev.event_number, lane)]
            for lane in range(1, 7)
            if (ev.event_number, lane) in lineups
            and lineups[(ev.event_number, lane)].get("athlete_ids")
        }
        if not ev_lanes:
            continue

        gender_label = "Girls" if ev.gender == "F" else "Boys"
        row_html: list[str] = []

        for lane in range(1, 7):
            data = ev_lanes.get(lane)
            if data:
                team_str = html.escape(data["team_id"])
                athlete_ids = data["athlete_ids"]
                relay_letter = data.get("relay_letter")
                if ev.event_type == EventType.RELAY and relay_letter:
                    participant = f"Relay {relay_letter} ({', '.join(athlete_ids)})"
                else:
                    participant = ", ".join(athlete_ids)
                participant_str = html.escape(participant)
                exh_str = "EXH" if data.get("is_exhibition") else ""
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
              <h3>Event {ev.event_number}: {gender_label} {html.escape(ev.name)}</h3>
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
      background: #eee;
      padding: 4px 8px;
      border-left: 4px solid #222;
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
      color: #555;
      border-bottom: 1px solid #999;
    }}
    .center {{ text-align: center; }}
    .write-in {{ border-left: 1px solid #ddd; }}
    @media print {{
      body {{ margin: 0; max-width: 100%; }}
      .event-block h3 {{ background: #f2f2f2; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
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
    lineups: dict[tuple[int, int], dict],
    meet_date: date | None = None,
) -> str:
    """Generates a 6-page print-ready HTML packet (one 24-event timer sheet per lane)."""
    date_display = (meet_date or date.today()).strftime("%B %d, %Y")
    esc_a = html.escape(team_a)
    esc_b = html.escape(team_b)

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
                    f"<td>{ev_label}</td>"
                    f"<td colspan='5' class='center'><em>Diving Break — No Lane Timing</em></td>"
                    f"</tr>"
                )
                continue

            data = lineups.get((ev.event_number, lane))
            if data and data.get("athlete_ids"):
                athlete_ids = data["athlete_ids"]
                relay_letter = data.get("relay_letter")
                if ev.event_type == EventType.RELAY and relay_letter:
                    participant = f"Relay {relay_letter}: {', '.join(athlete_ids)}"
                else:
                    participant = ", ".join(athlete_ids)
                swimmer_str = html.escape(participant)
                note_str = "EXH" if data.get("is_exhibition") else ""
            else:
                swimmer_str = ""
                note_str = ""

            row_html.append(
                f"<tr>"
                f"<td class='center'><strong>{ev.event_number}</strong></td>"
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
                    <th style="width: 24%;">Event</th>
                    <th style="width: 32%;">Swimmer / Relay</th>
                    <th class="center" style="width: 11%;">Watch 1</th>
                    <th class="center" style="width: 11%;">Watch 2</th>
                    <th class="center" style="width: 11%;">Watch 3</th>
                    <th class="center" style="width: 6%;">Note</th>
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
      background: #eee;
      color: #222;
    }}
    td.swimmer {{
      font-size: 10.5px;
    }}
    td.watch {{
      height: 19px;
    }}
    tr.diving-row td {{
      background: #f3f3f3;
      color: #555;
      padding: 3px 5px;
    }}
    .center {{ text-align: center; }}
    @media print {{
      body {{ padding: 0; }}
      .lane-page {{ max-width: 100%; margin: 0; }}
      th, tr.diving-row td {{
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
