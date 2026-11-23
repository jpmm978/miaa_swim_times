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
