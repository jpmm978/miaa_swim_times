import uuid
import streamlit as st

from models import Entry, Event, EventType, Result, ResultStatus
from report_export import export_meet_html
from scoring import MeetFormat, score_event
from sdif_export import export_meet_sd3
from storage import (
    clear_all,
    clear_event,
    export_meet_csv,
    init_db,
    load_all_data,
    load_rosters,
    load_team_names,
    parse_roster_csv,
    save_entry_and_result,
    save_roster,
    save_team_names,
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
            save_roster(team_a, parsed)
            st.success(f"Loaded {len(parsed)} swimmers for {team_a}.")
            st.rerun()

        file_b = st.file_uploader(f"{team_b} Roster", type=["csv"], key="roster_upload_b")
        if file_b is not None and st.button(f"Load {team_b} Roster"):
            parsed = parse_roster_csv(file_b.getvalue())
            save_roster(team_b, parsed)
            st.success(f"Loaded {len(parsed)} swimmers for {team_b}.")
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
    csv_data = export_meet_csv(STANDARD_EVENTS, entries, results)
    st.download_button(
        label="Export Results (CSV)",
        data=csv_data,
        file_name=f"meet_results_{team_a}_vs_{team_b}.csv".replace(" ", "_"),
        mime="text/csv",
        disabled=len(results) == 0,
    )

    sd3_data = export_meet_sd3(
        meet_name=f"{team_a} vs {team_b}",
        events=STANDARD_EVENTS,
        entries=entries,
        results=results,
    )
    st.download_button(
        label="Export Hy-Tek (.sd3)",
        data=sd3_data,
        file_name=f"meet_results_{team_a}_vs_{team_b}.sd3".replace(" ", "_"),
        mime="text/plain",
        disabled=len(results) == 0,
    )

    html_report = export_meet_html(
        team_a=team_a,
        team_b=team_b,
        div_totals=div_totals,
        events=STANDARD_EVENTS,
        entries=entries,
        results=results,
    )
    st.download_button(
        label="Export Printable Report (HTML)",
        data=html_report,
        file_name=f"meet_summary_{team_a}_vs_{team_b}.html".replace(" ", "_"),
        mime="text/html",
        disabled=len(results) == 0,
    )

    if st.button("Reset Entire Meet", type="secondary"):
        clear_all()
        st.rerun()


# --- Main Area: Division Filter & Event Selection ---
st.title("MIAA / NFHS Dual Meet Scorer")

filter_col, event_col = st.columns([1, 3])
division_filter = filter_col.radio("Division Filter", ["All", "Girls", "Boys"], horizontal=True)

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
selected_idx = event_col.selectbox(
    "Select Event", range(len(filtered_events)), format_func=lambda i: event_labels[i]
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
        "Leave unused lanes blank. Odd lanes default to Visitor; even lanes default to Home. "
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
                "Pad Time",
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
                "Pad Time",
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
            default_team_idx = 0 if lane % 2 == 0 else 1  # Even = Home, Odd = Visitor
            default_team = teams[default_team_idx]
            lane_roster = rosters.get((default_team, selected_event.gender), [])
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
                    "Rly", value="A", key=f"{key_prefix}_rly", label_visibility="collapsed"
                )
                if lane_roster:
                    l_names = cols[3].multiselect(
                        "Swimmers",
                        options=lane_roster,
                        max_selections=4,
                        placeholder="Select 4 swimmers...",
                        key=f"{key_prefix}_names",
                        label_visibility="collapsed",
                    )
                else:
                    raw_names = cols[3].text_input(
                        "Swimmers",
                        placeholder="Smith, Jones, Lee, Patel",
                        key=f"{key_prefix}_names",
                        label_visibility="collapsed",
                    )
                    l_names = [n.strip() for n in raw_names.split(",") if n.strip()]

                l_pad = cols[4].text_input(
                    "Pad",
                    placeholder="1:45.20",
                    key=f"{key_prefix}_pad",
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
                l_exh = cols[8].checkbox("Exh", key=f"{key_prefix}_exh", label_visibility="collapsed")
                l_malf = cols[9].checkbox("Malf", key=f"{key_prefix}_malf", label_visibility="collapsed")
            else:
                l_relay = None
                if lane_roster:
                    selected_swimmer = cols[2].selectbox(
                        "Swimmer",
                        options=[""] + lane_roster,
                        key=f"{key_prefix}_names",
                        label_visibility="collapsed",
                    )
                    l_names = [selected_swimmer] if selected_swimmer else []
                else:
                    raw_name = cols[2].text_input(
                        "Swimmer",
                        placeholder="Last, First",
                        key=f"{key_prefix}_names",
                        label_visibility="collapsed",
                    )
                    l_names = [raw_name.strip()] if raw_name.strip() else []

                l_pad = cols[3].text_input(
                    "Pad",
                    placeholder="24.51",
                    key=f"{key_prefix}_pad",
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
                l_exh = cols[7].checkbox("Exh", key=f"{key_prefix}_exh", label_visibility="collapsed")
                l_malf = cols[8].checkbox("Malf", key=f"{key_prefix}_malf", label_visibility="collapsed")

            lane_inputs.append(
                {
                    "lane": lane,
                    "team": l_team,
                    "relay": l_relay,
                    "names": l_names,
                    "pad": l_pad,
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
                    pad_cs = parse_time_to_cs(row["pad"]) if row["pad"].strip() else None
                    backups_cs = [
                        parse_time_to_cs(t) for t in row["backups"].split(",") if t.strip()
                    ]
                except ValueError:
                    parse_errors.append(
                        f"Lane {row['lane']}: Invalid time format (use SS.cc or MM:SS.cc)."
                    )
                    continue

                official_cs = calculate_official_time(pad_cs, backups_cs, row["malf"])
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
                    pad_time_cs=pad_cs,
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

    rows = []
    for res in event_results:
        ent = event_entries[res.entry_id]
        perf_display = (
            f"{res.diving_score:.2f}"
            if selected_event.event_type == EventType.DIVING and res.diving_score is not None
            else (format_cs_to_time(res.official_time_cs) if res.official_time_cs is not None else "—")
        )
        participant_display = (
            f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
            if selected_event.event_type == EventType.RELAY and ent.relay_letter
            else ", ".join(ent.athlete_ids)
        )
        if res.place is not None:
            place_display = f"{res.place} (JD)" if res.manual_place is not None else str(res.place)
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

    if st.button(f"Clear Event {selected_event.event_number} Results"):
        clear_event(selected_event.event_number)
        st.rerun()
