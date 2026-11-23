from collections import Counter
import uuid
import streamlit as st

from models import Entry, Event, EventType, Result, ResultStatus
from report_export import (
    export_heat_sheet_html,
    export_lane_timer_sheets_html,
    export_meet_html,
)
from scoring import MeetFormat, score_event
from sdif_export import export_meet_sd3
from storage import (
    clear_all,
    clear_event,
    clear_lineups,
    delete_entry_and_result,
    export_meet_csv,
    init_db,
    load_all_data,
    load_lineups,
    load_rosters,
    load_team_names,
    parse_roster_csv,
    save_entry_and_result,
    save_lineups,
    save_roster,
    save_team_names,
    update_result_override,
)
from timing import calculate_official_time, format_cs_to_time, parse_time_to_cs
from validation import validate_athlete_entries

st.set_page_config(page_title="MIAA Dual Meet Scorer", layout="wide")
init_db()

BASE_EVENTS = [
    ("200 Medley Relay", EventType.RELAY),
    ("200 Freestyle", EventType.INDIVIDUAL),
    ("200 Individual Medley", EventType.INDIVIDUAL),
    ("50 Freestyle", EventType.INDIVIDUAL),
    ("1-Meter Diving", EventType.DIVING),
    ("100 Butterfly", EventType.INDIVIDUAL),
    ("100 Freestyle", EventType.INDIVIDUAL),
    ("500 Freestyle", EventType.INDIVIDUAL),
    ("200 Freestyle Relay", EventType.RELAY),
    ("100 Backstroke", EventType.INDIVIDUAL),
    ("100 Breaststroke", EventType.INDIVIDUAL),
    ("400 Freestyle Relay", EventType.RELAY),
]

JD_OPTIONS = ["Auto", 1, 2, 3, 4, 5, 6]


def build_miaa_events() -> list[Event]:
    """Generates the 24-event MIAA order with Girls' events preceding Boys' events."""
    events: list[Event] = []
    event_num = 1
    for name, ev_type in BASE_EVENTS:
        events.append(Event(event_num, name, ev_type, "F"))
        event_num += 1
        events.append(Event(event_num, name, ev_type, "M"))
        event_num += 1
    return events


STANDARD_EVENTS = build_miaa_events()
EVENTS_BY_NUM = {e.event_number: e for e in STANDARD_EVENTS}

# Load persisted state from SQLite on every run
team_a_saved, team_b_saved = load_team_names()
entries, results = load_all_data()
rosters = load_rosters()
lineups = load_lineups()


def compute_division_totals(team_a: str, team_b: str) -> dict[str, dict[str, float]]:
    """Scores all 24 events in place and returns separate totals for Girls ('F') and Boys ('M')."""
    totals = {
        "F": {team_a: 0.0, team_b: 0.0},
        "M": {team_a: 0.0, team_b: 0.0},
    }
    for ev in STANDARD_EVENTS:
        ev_scores = score_event(
            event=ev,
            entries=entries,
            results=results,
            meet_format=MeetFormat.DUAL,
        )
        for team_id, pts in ev_scores.items():
            totals[ev.gender][team_id] = totals[ev.gender].get(team_id, 0.0) + pts
    return totals


def get_athlete_usage() -> list[dict[str, str]]:
    """Builds a summary table of each athlete's total and individual event counts."""
    athletes = sorted({ath for e in entries for ath in e.athlete_ids})
    summary = []
    for ath in athletes:
        ath_entries = [e for e in entries if ath in e.athlete_ids]
        total = len(ath_entries)
        indiv = sum(
            1
            for e in ath_entries
            if EVENTS_BY_NUM[e.event_number].event_type in (EventType.INDIVIDUAL, EventType.DIVING)
        )
        summary.append(
            {
                "Athlete": ath,
                "Total (Max 4)": f"{total}/4",
                "Indiv (Max 2)": f"{indiv}/2",
            }
        )
    return summary


# --- Sidebar: Team Setup, Rosters, Division Scoreboards, Usage Tracker & Exports ---
with st.sidebar:
    st.header("Meet Setup")
    team_a = st.text_input("Team A (Home - Even Lanes)", value=team_a_saved)
    team_b = st.text_input("Team B (Visitor - Odd Lanes)", value=team_b_saved)
    if (team_a, team_b) != (team_a_saved, team_b_saved):
        save_team_names(team_a, team_b)

    with st.expander("Import Team Rosters (CSV)"):
        st.caption("CSV columns: `Name,Gender` (`F`/`M`)")

        file_a = st.file_uploader(f"{team_a} Roster", type=["csv"], key="roster_upload_a")
        if file_a is not None and st.button(f"Load {team_a} Roster"):
            parsed = parse_roster_csv(file_a.getvalue())
            if not parsed:
                st.error("No valid swimmers found. Check that each row has a Name and Gender (F/M).")
            else:
                save_roster(team_a, parsed)
                st.rerun()

        file_b = st.file_uploader(f"{team_b} Roster", type=["csv"], key="roster_upload_b")
        if file_b is not None and st.button(f"Load {team_b} Roster"):
            parsed = parse_roster_csv(file_b.getvalue())
            if not parsed:
                st.error("No valid swimmers found. Check that each row has a Name and Gender (F/M).")
            else:
                save_roster(team_b, parsed)
                st.rerun()

        count_a = len(rosters.get((team_a, "F"), [])) + len(rosters.get((team_a, "M"), []))
        count_b = len(rosters.get((team_b, "F"), [])) + len(rosters.get((team_b, "M"), []))
        st.caption(f"Saved: {team_a} ({count_a}) | {team_b} ({count_b})")

    st.divider()
    st.header("Live Meet Scores")
    div_totals = compute_division_totals(team_a, team_b)

    st.subheader("Girls Division")
    g1, g2 = st.columns(2)
    g1.metric(team_a, f"{div_totals['F'].get(team_a, 0.0):g}")
    g2.metric(team_b, f"{div_totals['F'].get(team_b, 0.0):g}")

    st.subheader("Boys Division")
    b1, b2 = st.columns(2)
    b1.metric(team_a, f"{div_totals['M'].get(team_a, 0.0):g}")
    b2.metric(team_b, f"{div_totals['M'].get(team_b, 0.0):g}")

    st.divider()
    with st.expander("Athlete Event Counts (NFHS 3-2-1)"):
        usage = get_athlete_usage()
        if usage:
            st.table(usage)
        else:
            st.caption("No athletes recorded yet.")

    st.divider()
    st.subheader("Export Results")

    def _division_slice(gender: str) -> tuple[list[Event], list[Entry], list[Result]]:
        div_events = [e for e in STANDARD_EVENTS if e.gender == gender]
        div_event_nums = {e.event_number for e in div_events}
        div_entries = [e for e in entries if e.event_number in div_event_nums]
        div_entry_ids = {e.entry_id for e in div_entries}
        div_results = [r for r in results if r.entry_id in div_entry_ids]
        return div_events, div_entries, div_results

    g_events, g_entries, g_results = _division_slice("F")
    b_events, b_entries, b_results = _division_slice("M")
    safe_matchup = f"{team_a}_vs_{team_b}".replace(" ", "_")

    # --- 1-Page Printable Reports (HTML) ---
    st.caption("1-Page Official Report (HTML)")
    h1, h2 = st.columns(2)
    h1.download_button(
        label="Girls HTML",
        data=export_meet_html(
            team_a=team_a,
            team_b=team_b,
            div_totals=div_totals,
            events=STANDARD_EVENTS,
            entries=entries,
            results=results,
            gender="F",
        ),
        file_name=f"girls_report_{safe_matchup}.html",
        mime="text/html",
        disabled=len(g_results) == 0,
        use_container_width=True,
    )
    h2.download_button(
        label="Boys HTML",
        data=export_meet_html(
            team_a=team_a,
            team_b=team_b,
            div_totals=div_totals,
            events=STANDARD_EVENTS,
            entries=entries,
            results=results,
            gender="M",
        ),
        file_name=f"boys_report_{safe_matchup}.html",
        mime="text/html",
        disabled=len(b_results) == 0,
        use_container_width=True,
    )

    # --- CSV Exports ---
    st.caption("Results Spreadsheet (CSV)")
    c1, c2 = st.columns(2)
    c1.download_button(
        label="Girls CSV",
        data=export_meet_csv(g_events, g_entries, g_results),
        file_name=f"girls_results_{safe_matchup}.csv",
        mime="text/csv",
        disabled=len(g_results) == 0,
        use_container_width=True,
    )
    c2.download_button(
        label="Boys CSV",
        data=export_meet_csv(b_events, b_entries, b_results),
        file_name=f"boys_results_{safe_matchup}.csv",
        mime="text/csv",
        disabled=len(b_results) == 0,
        use_container_width=True,
    )

    # --- Hy-Tek (.sd3) Exports ---
    st.caption("Hy-Tek Team Manager (.sd3)")
    s1, s2 = st.columns(2)
    s1.download_button(
        label="Girls .sd3",
        data=export_meet_sd3(
            meet_name=f"{team_a} vs {team_b} (Girls)",
            events=g_events,
            entries=g_entries,
            results=g_results,
        ),
        file_name=f"girls_results_{safe_matchup}.sd3",
        mime="text/plain",
        disabled=len(g_results) == 0,
        use_container_width=True,
    )
    s2.download_button(
        label="Boys .sd3",
        data=export_meet_sd3(
            meet_name=f"{team_a} vs {team_b} (Boys)",
            events=b_events,
            entries=b_entries,
            results=b_results,
        ),
        file_name=f"boys_results_{safe_matchup}.sd3",
        mime="text/plain",
        disabled=len(b_results) == 0,
        use_container_width=True,
    )
    if st.button("Reset Entire Meet", type="secondary"):
        clear_all()
        st.rerun()


# --- Main Area: Tabs ---
st.title("MIAA / NFHS Dual Meet Scorer")
tab_scoring, tab_lineup = st.tabs(["Event Scoring", "Batch Lineup & Seeding"])


# ==============================================================================
# TAB 1: EVENT SCORING
# ==============================================================================
with tab_scoring:
    division_filter = st.radio("Division Filter", ["All", "Girls", "Boys"], horizontal=True)

    filtered_events = [
        e
        for e in STANDARD_EVENTS
        if division_filter == "All"
        or (division_filter == "Girls" and e.gender == "F")
        or (division_filter == "Boys" and e.gender == "M")
    ]

    event_labels = [
        f"Event {e.event_number}: {'Girls' if e.gender == 'F' else 'Boys'} {e.name}"
        for e in filtered_events
    ]

    if "scoring_event_idx" not in st.session_state:
        st.session_state.scoring_event_idx = 0

    if st.session_state.scoring_event_idx >= len(filtered_events):
        st.session_state.scoring_event_idx = 0

    def _prev_event() -> None:
        st.session_state.scoring_event_idx = max(0, st.session_state.scoring_event_idx - 1)

    def _next_event(max_idx: int) -> None:
        st.session_state.scoring_event_idx = min(max_idx, st.session_state.scoring_event_idx + 1)

    nav_prev, nav_select, nav_next = st.columns([1, 4, 1], vertical_alignment="bottom")

    nav_prev.button(
        "⬅️ Prev Event",
        on_click=_prev_event,
        disabled=st.session_state.scoring_event_idx == 0,
        use_container_width=True,
    )
    selected_idx = nav_select.selectbox(
        "Select Event",
        range(len(filtered_events)),
        format_func=lambda i: event_labels[i],
        key="scoring_event_idx",
    )
    nav_next.button(
        "Next Event ➡️",
        on_click=_next_event,
        args=(len(filtered_events) - 1,),
        disabled=st.session_state.scoring_event_idx >= len(filtered_events) - 1,
        use_container_width=True,
    )

    selected_event = filtered_events[selected_idx]
    gender_label = "Girls" if selected_event.gender == "F" else "Boys"

    # --- Entry Section: Diving (Single Form) vs. Swimming (6-Lane Heat Grid) ---
    if selected_event.event_type == EventType.DIVING:
        st.subheader(f"Add Diving Score — {gender_label} {selected_event.name}")
        with st.form("diving_form", clear_on_submit=True):
            d1, d2, d3, d4, d5, d6 = st.columns([1.8, 2, 1.3, 0.9, 0.8, 0.8])
            team_choice = d1.selectbox("Team", [team_a, team_b])
            diver_name = d2.text_input("Diver Name (Last, First)")
            diving_score = d3.number_input("Total Score", min_value=0.0, step=0.05, format="%.2f")
            status_choice = d4.selectbox("Status", [s.value for s in ResultStatus])
            jd_choice = d5.selectbox("JD Place", JD_OPTIONS)
            is_exhibition = d6.checkbox("Exhibition")
            override_limits = st.checkbox("Override NFHS entry limit warnings")

            if st.form_submit_button("Record Dive Score", type="primary"):
                if not diver_name.strip():
                    st.error("Please enter a diver name.")
                else:
                    entry_id = str(uuid.uuid4())[:8]
                    new_entry = Entry(
                        entry_id=entry_id,
                        event_number=selected_event.event_number,
                        team_id=team_choice,
                        athlete_ids=[diver_name.strip()],
                        is_exhibition=is_exhibition,
                    )
                    violations = validate_athlete_entries(
                        diver_name.strip(), entries + [new_entry], EVENTS_BY_NUM
                    )
                    if violations and not override_limits:
                        for msg in violations:
                            st.warning(f"NFHS Rule 3-2-1 Violation: {msg}")
                        st.error("Entry blocked. Check override to record anyway.")
                    else:
                        new_result = Result(
                            entry_id=entry_id,
                            diving_score=diving_score,
                            status=ResultStatus(status_choice),
                            manual_place=None if jd_choice == "Auto" else int(jd_choice),
                        )
                        save_entry_and_result(new_entry, new_result)
                        st.rerun()
    else:
        is_relay = selected_event.event_type == EventType.RELAY
        st.subheader(f"6-Lane Heat Entry — {gender_label} {selected_event.name}")
        st.caption(
            "Pre-filled from Batch Lineup if saved. Leave unused lanes blank. "
            "Use JD only for an official Judge's Decision place override."
        )

        with st.form(f"heat_grid_ev_{selected_event.event_number}", clear_on_submit=True):
            if is_relay:
                col_spec = [0.45, 1.3, 0.55, 2.1, 1.0, 1.4, 0.85, 0.75, 0.45, 0.5]
                headers = [
                    "Lane",
                    "Team",
                    "Rly",
                    "Swimmers (comma-sep)",
                    "Watch Time",
                    "Backups (csv)",
                    "Status",
                    "JD",
                    "Exh",
                    "Malf",
                ]
            else:
                col_spec = [0.45, 1.4, 2.3, 1.1, 1.6, 0.85, 0.75, 0.45, 0.5]
                headers = [
                    "Lane",
                    "Team",
                    "Swimmer (Last, First)",
                    "Watch Time",
                    "Backups (csv)",
                    "Status",
                    "JD",
                    "Exh",
                    "Malf",
                ]

            header_cols = st.columns(col_spec)
            for col, label in zip(header_cols, headers):
                col.markdown(f"**{label}**")

            lane_inputs = []
            teams = [team_a, team_b]
            statuses = [s.value for s in ResultStatus]

            for lane in range(1, 7):
                cols = st.columns(col_spec)
                saved = lineups.get((selected_event.event_number, lane), {})
                default_team_idx = 0 if lane % 2 == 0 else 1  # Even = Home, Odd = Visitor
                if saved.get("team_id") in teams:
                    default_team_idx = teams.index(saved["team_id"])
                default_team = teams[default_team_idx]
                lane_roster = rosters.get((default_team, selected_event.gender), [])
                saved_names = saved.get("athlete_ids", [])
                key_prefix = f"ev{selected_event.event_number}_l{lane}"

                cols[0].markdown(f"### {lane}")
                l_team = cols[1].selectbox(
                    "Team",
                    teams,
                    index=default_team_idx,
                    key=f"{key_prefix}_team",
                    label_visibility="collapsed",
                )

                if is_relay:
                    l_relay = cols[2].text_input(
                        "Rly",
                        value=saved.get("relay_letter") or "A",
                        key=f"{key_prefix}_rly",
                        label_visibility="collapsed",
                    )
                    if lane_roster:
                        l_names = cols[3].multiselect(
                            "Swimmers",
                            options=lane_roster,
                            default=[n for n in saved_names if n in lane_roster],
                            max_selections=4,
                            placeholder="Select 4 swimmers...",
                            key=f"{key_prefix}_names",
                            label_visibility="collapsed",
                        )
                    else:
                        raw_names = cols[3].text_input(
                            "Swimmers",
                            value=", ".join(saved_names),
                            placeholder="Smith, Jones, Lee, Patel",
                            key=f"{key_prefix}_names",
                            label_visibility="collapsed",
                        )
                        l_names = [n.strip() for n in raw_names.split(",") if n.strip()]

                    l_watch = cols[4].text_input(
                        "Watch",
                        placeholder="1:45.20",
                        key=f"{key_prefix}_watch",
                        label_visibility="collapsed",
                    )
                    l_backups = cols[5].text_input(
                        "Backups",
                        placeholder="1:45.21, 1:45.25",
                        key=f"{key_prefix}_bkp",
                        label_visibility="collapsed",
                    )
                    l_status = cols[6].selectbox(
                        "Status", statuses, key=f"{key_prefix}_stat", label_visibility="collapsed"
                    )
                    l_jd = cols[7].selectbox(
                        "JD", JD_OPTIONS, key=f"{key_prefix}_jd", label_visibility="collapsed"
                    )
                    l_exh = cols[8].checkbox(
                        "Exh",
                        value=saved.get("is_exhibition", False),
                        key=f"{key_prefix}_exh",
                        label_visibility="collapsed",
                    )
                    l_malf = cols[9].checkbox(
                        "Malf", key=f"{key_prefix}_malf", label_visibility="collapsed"
                    )
                else:
                    l_relay = None
                    if lane_roster:
                        opts = [""] + lane_roster
                        saved_single = (
                            saved_names[0] if saved_names and saved_names[0] in opts else ""
                        )
                        selected_swimmer = cols[2].selectbox(
                            "Swimmer",
                            options=opts,
                            index=opts.index(saved_single),
                            key=f"{key_prefix}_names",
                            label_visibility="collapsed",
                        )
                        l_names = [selected_swimmer] if selected_swimmer else []
                    else:
                        raw_name = cols[2].text_input(
                            "Swimmer",
                            value=saved_names[0] if saved_names else "",
                            placeholder="Last, First",
                            key=f"{key_prefix}_names",
                            label_visibility="collapsed",
                        )
                        l_names = [raw_name.strip()] if raw_name.strip() else []

                    l_watch = cols[3].text_input(
                        "Watch",
                        placeholder="24.51",
                        key=f"{key_prefix}_watch",
                        label_visibility="collapsed",
                    )
                    l_backups = cols[4].text_input(
                        "Backups",
                        placeholder="24.51, 24.52",
                        key=f"{key_prefix}_bkp",
                        label_visibility="collapsed",
                    )
                    l_status = cols[5].selectbox(
                        "Status", statuses, key=f"{key_prefix}_stat", label_visibility="collapsed"
                    )
                    l_jd = cols[6].selectbox(
                        "JD", JD_OPTIONS, key=f"{key_prefix}_jd", label_visibility="collapsed"
                    )
                    l_exh = cols[7].checkbox(
                        "Exh",
                        value=saved.get("is_exhibition", False),
                        key=f"{key_prefix}_exh",
                        label_visibility="collapsed",
                    )
                    l_malf = cols[8].checkbox(
                        "Malf", key=f"{key_prefix}_malf", label_visibility="collapsed"
                    )

                lane_inputs.append(
                    {
                        "lane": lane,
                        "team": l_team,
                        "relay": l_relay,
                        "names": l_names,
                        "watch": l_watch,
                        "backups": l_backups,
                        "status": l_status,
                        "jd": None if l_jd == "Auto" else int(l_jd),
                        "exh": l_exh,
                        "malf": l_malf,
                    }
                )

            override_limits = st.checkbox("Override NFHS entry limit warnings for this heat")
            submitted_heat = st.form_submit_button("Record Heat Results", type="primary")

            if submitted_heat:
                pending_pairs: list[tuple[Entry, Result]] = []
                parse_errors: list[str] = []

                for row in lane_inputs:
                    athlete_list = row["names"]
                    if not athlete_list:
                        continue  # Skip empty lane

                    try:
                        watch_cs = parse_time_to_cs(row["watch"]) if row["watch"].strip() else None
                        backups_cs = [
                            parse_time_to_cs(t) for t in row["backups"].split(",") if t.strip()
                        ]
                    except ValueError:
                        parse_errors.append(
                            f"Lane {row['lane']}: Invalid time format (use SS.cc or MM:SS.cc)."
                        )
                        continue

                    official_cs = calculate_official_time(watch_cs, backups_cs, row["malf"])
                    entry_id = str(uuid.uuid4())[:8]

                    new_entry = Entry(
                        entry_id=entry_id,
                        event_number=selected_event.event_number,
                        team_id=row["team"],
                        athlete_ids=athlete_list,
                        is_exhibition=row["exh"],
                        relay_letter=row["relay"].strip() if row["relay"] else None,
                    )
                    new_result = Result(
                        entry_id=entry_id,
                        watch_time_cs=watch_cs,
                        backup_times_cs=backups_cs,
                        status=ResultStatus(row["status"]),
                        official_time_cs=official_cs,
                        manual_place=row["jd"],
                    )
                    pending_pairs.append((new_entry, new_result))

                if parse_errors:
                    for err in parse_errors:
                        st.error(err)
                elif not pending_pairs:
                    st.warning("No swimmers entered. Fill in at least one lane before recording.")
                else:
                    projected_entries = entries + [pair[0] for pair in pending_pairs]
                    heat_athletes = sorted(
                        {ath for pair in pending_pairs for ath in pair[0].athlete_ids}
                    )
                    violations: list[str] = []
                    for ath_id in heat_athletes:
                        violations.extend(
                            validate_athlete_entries(ath_id, projected_entries, EVENTS_BY_NUM)
                        )

                    if violations and not override_limits:
                        for msg in violations:
                            st.warning(f"NFHS Rule 3-2-1 Violation: {msg}")
                        st.error(
                            "Heat blocked. Fix the lineup or check 'Override NFHS entry limit warnings' to save anyway."
                        )
                    else:
                        for ent, res in pending_pairs:
                            save_entry_and_result(ent, res)
                        st.rerun()

    # --- Event Results Table ---
    st.divider()
    st.subheader(
        f"Official Results — Event {selected_event.event_number}: {gender_label} {selected_event.name}"
    )

    event_entries = {e.entry_id: e for e in entries if e.event_number == selected_event.event_number}
    event_results = [r for r in results if r.entry_id in event_entries]

    if not event_results:
        st.info("No results recorded for this event yet.")
    else:
        event_results.sort(key=lambda r: (r.place is None, r.place or 999))

        place_counts = Counter(r.place for r in event_results if r.place is not None)
        tied_places = {p for p, count in place_counts.items() if count > 1}

        rows = []
        for res in event_results:
            ent = event_entries[res.entry_id]
            perf_display = (
                f"{res.diving_score:.2f}"
                if selected_event.event_type == EventType.DIVING and res.diving_score is not None
                else (
                    format_cs_to_time(res.official_time_cs)
                    if res.official_time_cs is not None
                    else "—"
                )
            )
            participant_display = (
                f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
                if selected_event.event_type == EventType.RELAY and ent.relay_letter
                else ", ".join(ent.athlete_ids)
            )
            if res.place is not None:
                tie_star = "*" if res.place in tied_places else ""
                place_display = (
                    f"{res.place}{tie_star} (JD)"
                    if res.manual_place is not None
                    else f"{res.place}{tie_star}"
                )
            else:
                place_display = "—"

            rows.append(
                {
                    "Place": place_display,
                    "Team": ent.team_id,
                    "Participant": participant_display,
                    "Official Time / Score": perf_display,
                    "Status": res.status.value,
                    "Exh": "Yes" if ent.is_exhibition else "",
                    "Points": f"{res.points:g}",
                }
            )

        st.table(rows)

        if tied_places:
            st.caption(
                "*Note: Per MIAA / NFHS Swimming & Diving Rule 7-1 (Scoring), when competitors "
                "tie for a scoring place, the points for the tied place and the next consecutive "
                "place(s) are combined and divided equally among the tied competitors."
            )

        result_options = {
            res.entry_id: (
                f"{event_entries[res.entry_id].team_id} — "
                f"{', '.join(event_entries[res.entry_id].athlete_ids)} "
                f"(Current Place: {res.place if res.place is not None else '—'}"
                f"{' JD' if res.manual_place is not None else ''})"
            )
            for res in event_results
        }
        results_by_id = {res.entry_id: res for res in event_results}

        with st.expander("Edit Official Judge's Decision (JD) Override"):
            selected_entry_id = st.selectbox(
                "Select Swimmer / Relay",
                options=list(result_options.keys()),
                format_func=lambda eid: result_options[eid],
                key=f"jd_edit_select_ev_{selected_event.event_number}",
            )
            current_res = results_by_id[selected_entry_id]
            current_jd_idx = (
                JD_OPTIONS.index(current_res.manual_place)
                if current_res.manual_place in JD_OPTIONS
                else 0
            )

            with st.form(f"jd_edit_form_ev_{selected_event.event_number}"):
                e1, e2 = st.columns([1, 2])
                new_jd = e1.selectbox(
                    "JD Place (choose Auto to clear)",
                    options=JD_OPTIONS,
                    index=current_jd_idx,
                )
                new_note = e2.text_input(
                    "Official Note (optional)",
                    value=current_res.override_note,
                    placeholder="e.g., Watch malfunction - visual 1st",
                )

                if st.form_submit_button("Save JD Override", type="primary"):
                    update_result_override(
                        entry_id=selected_entry_id,
                        manual_place=None if new_jd == "Auto" else int(new_jd),
                        override_note=new_note,
                    )
                    st.rerun()

        with st.expander("Delete a Single Result"):
            delete_entry_id = st.selectbox(
                "Select Swimmer / Relay to Remove",
                options=list(result_options.keys()),
                format_func=lambda eid: result_options[eid],
                key=f"del_select_ev_{selected_event.event_number}",
            )
            if st.button(
                "Delete Selected Result",
                type="secondary",
                key=f"del_btn_ev_{selected_event.event_number}",
            ):
                delete_entry_and_result(delete_entry_id)
                st.rerun()

        if st.button(f"Clear Event {selected_event.event_number} Results"):
            clear_event(selected_event.event_number)
            st.rerun()


# ==============================================================================
# TAB 2: BATCH LINEUP & SEEDING
# ==============================================================================
with tab_lineup:
    st.subheader("Batch Lineup & Seeding")
    st.caption(
        "Assign swimmers and lanes across all swimming events. "
        "Saved lineups automatically pre-fill the Event Scoring tab and are checked against NFHS Rule 3-2-1 (max 4 total / 2 individual)."
    )

    lu_filter_col, lu_heat_col, lu_timer_col = st.columns([2.2, 1.4, 1.4])
    lineup_div = lu_filter_col.radio(
        "Show Division", ["All", "Girls", "Boys"], horizontal=True, key="lineup_div_filter"
    )

    heat_sheet_html = export_heat_sheet_html(
        team_a=team_a,
        team_b=team_b,
        events=STANDARD_EVENTS,
        lineups=lineups,
    )
    lu_heat_col.download_button(
        label="Export Heat Sheet (HTML)",
        data=heat_sheet_html,
        file_name=f"heat_sheet_{team_a}_vs_{team_b}.html".replace(" ", "_"),
        mime="text/html",
        disabled=len(lineups) == 0,
        use_container_width=True,
    )

    timer_sheets_html = export_lane_timer_sheets_html(
        team_a=team_a,
        team_b=team_b,
        events=STANDARD_EVENTS,
        lineups=lineups,
    )
    lu_timer_col.download_button(
        label="Export Lane Timer Sheets (HTML)",
        data=timer_sheets_html,
        file_name=f"lane_timer_sheets_{team_a}_vs_{team_b}.html".replace(" ", "_"),
        mime="text/html",
        use_container_width=True,
    )

    lineup_events = [
        e
        for e in STANDARD_EVENTS
        if e.event_type != EventType.DIVING
        and (
            lineup_div == "All"
            or (lineup_div == "Girls" and e.gender == "F")
            or (lineup_div == "Boys" and e.gender == "M")
        )
    ]

    teams = [team_a, team_b]
    pending_lineups: list[dict] = []

    with st.form("batch_lineup_form"):
        for ev in lineup_events:
            g_label = "Girls" if ev.gender == "F" else "Boys"
            is_rly = ev.event_type == EventType.RELAY

            with st.expander(f"Event {ev.event_number}: {g_label} {ev.name}", expanded=False):
                for lane in range(1, 7):
                    saved = lineups.get((ev.event_number, lane), {})
                    default_team_idx = 0 if lane % 2 == 0 else 1
                    if saved.get("team_id") in teams:
                        default_team_idx = teams.index(saved["team_id"])

                    if is_rly:
                        c_lane, c_team, c_rly, c_swimmer, c_exh = st.columns([0.5, 1.3, 0.55, 2.7, 0.55])
                    else:
                        c_lane, c_team, c_swimmer, c_exh = st.columns([0.5, 1.4, 3.1, 0.6])

                    c_lane.markdown(f"**L{lane}**")

                    l_team = c_team.selectbox(
                        "Team",
                        teams,
                        index=default_team_idx,
                        key=f"lu_ev{ev.event_number}_l{lane}_team",
                        label_visibility="collapsed",
                    )
                    lane_roster = rosters.get((l_team, ev.gender), [])
                    saved_names = saved.get("athlete_ids", [])

                    if is_rly:
                        l_relay = c_rly.text_input(
                            "Rly",
                            value=saved.get("relay_letter") or "A",
                            key=f"lu_ev{ev.event_number}_l{lane}_rly",
                            label_visibility="collapsed",
                        )
                        if lane_roster:
                            l_names = c_swimmer.multiselect(
                                "Swimmers",
                                options=lane_roster,
                                default=[n for n in saved_names if n in lane_roster],
                                max_selections=4,
                                placeholder="Select 4 relay swimmers...",
                                key=f"lu_ev{ev.event_number}_l{lane}_names",
                                label_visibility="collapsed",
                            )
                        else:
                            raw_rly = c_swimmer.text_input(
                                "Swimmers",
                                value=", ".join(saved_names),
                                placeholder="Smith, Jones, Lee, Patel",
                                key=f"lu_ev{ev.event_number}_l{lane}_names",
                                label_visibility="collapsed",
                            )
                            l_names = [n.strip() for n in raw_rly.split(",") if n.strip()]
                    else:
                        l_relay = None
                        if lane_roster:
                            opts = [""] + lane_roster
                            saved_single = (
                                saved_names[0] if saved_names and saved_names[0] in opts else ""
                            )
                            picked = c_swimmer.selectbox(
                                "Swimmer",
                                options=opts,
                                index=opts.index(saved_single),
                                key=f"lu_ev{ev.event_number}_l{lane}_names",
                                label_visibility="collapsed",
                            )
                            l_names = [picked] if picked else []
                        else:
                            raw_ind = c_swimmer.text_input(
                                "Swimmer",
                                value=saved_names[0] if saved_names else "",
                                placeholder="Last, First",
                                key=f"lu_ev{ev.event_number}_l{lane}_names",
                                label_visibility="collapsed",
                            )
                            l_names = [raw_ind.strip()] if raw_ind.strip() else []

                    l_exh = c_exh.checkbox(
                        "Exh",
                        value=saved.get("is_exhibition", False),
                        key=f"lu_ev{ev.event_number}_l{lane}_exh",
                        label_visibility="collapsed",
                    )

                    pending_lineups.append(
                        {
                            "event_number": ev.event_number,
                            "lane": lane,
                            "team_id": l_team,
                            "athlete_ids": l_names,
                            "relay_letter": l_relay.strip() if l_relay else None,
                            "is_exhibition": l_exh,
                        }
                    )

        override_lineup_limits = st.checkbox(
            "Override NFHS entry limit warnings for this lineup"
        )
        submitted_lineups = st.form_submit_button("Save All Lineups", type="primary")

        if submitted_lineups:
            merged_lineups = dict(lineups)
            for row in pending_lineups:
                key = (row["event_number"], row["lane"])
                if row["athlete_ids"]:
                    merged_lineups[key] = row
                else:
                    merged_lineups.pop(key, None)

            projected_lineup_entries = [
                Entry(
                    entry_id=f"lu_{ev_num}_{lane}",
                    event_number=ev_num,
                    team_id=data["team_id"],
                    athlete_ids=data["athlete_ids"],
                    is_exhibition=data.get("is_exhibition", False),
                    relay_letter=data.get("relay_letter"),
                )
                for (ev_num, lane), data in merged_lineups.items()
                if data.get("athlete_ids")
            ]

            lineup_athletes = sorted(
                {ath for e in projected_lineup_entries for ath in e.athlete_ids}
            )
            violations: list[str] = []
            for ath_id in lineup_athletes:
                violations.extend(
                    validate_athlete_entries(ath_id, projected_lineup_entries, EVENTS_BY_NUM)
                )

            if violations and not override_lineup_limits:
                for msg in violations:
                    st.warning(f"NFHS Rule 3-2-1 Violation: {msg}")
                st.error(
                    "Lineup not saved. Fix the entries above or check 'Override NFHS entry limit warnings' to save anyway."
                )
            else:
                save_lineups(pending_lineups)
                st.success("Lineups saved and synced to Event Scoring.")
                st.rerun()

    st.divider()
    if st.button(
        "Clear All Lineups",
        type="secondary",
        disabled=len(lineups) == 0,
        help="Clears all saved lane assignments across all events. Rosters and recorded results are not affected.",
    ):
        clear_lineups()
        for key in list(st.session_state.keys()):
            if key.startswith("lu_ev"):
                del st.session_state[key]
        st.rerun()
