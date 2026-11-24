from collections import Counter
import inspect
import time
import uuid
import streamlit as st
import streamlit.components.v1 as components

from models import Entry, Event, EventType, Result, ResultStatus
try:
    from report_export import (
        export_event_pair_timer_sheets_html,
        export_heat_sheet_html,
        export_lane_event_pair_sheets_html,
        export_lane_timer_sheets_html,
        export_meet_html,
    )
except ImportError:
    from reports_exports import (  # type: ignore[no-redef]
        export_event_pair_timer_sheets_html,
        export_heat_sheet_html,
        export_lane_event_pair_sheets_html,
        export_lane_timer_sheets_html,
        export_meet_html,
    )
from scoring import MeetFormat, score_event
from sdif_export import export_meet_sd3
from storage import (
    add_roster_swimmer,
    clear_all,
    clear_event,
    clear_lineups,
    create_new_meet,
    delete_meet,
    delete_meet_signature,
    export_full_backup_json,
    export_meet_csv,
    get_active_meet_id,
    init_db,
    list_meets,
    load_all_data,
    load_lineups,
    load_meet_signatures,
    load_rosters,
    load_team_names,
    parse_roster_csv,
    rename_meet,
    restore_full_backup_json,
    save_entry_and_result,
    save_lineups,
    save_meet_signature,
    save_roster,
    save_team_names,
    set_active_meet,
    set_meet_status,
    update_entry_and_result,
)
from timing import calculate_official_time, format_cs_to_time, parse_time_to_cs
from validation import validate_athlete_entries

st.set_page_config(page_title="MIAA Dual Meet Scorer", layout="wide")

st.markdown(
    """
    <style>
      div[data-testid="stTable"] table {
        border-collapse: collapse;
        width: 100%;
      }
      div[data-testid="stTable"] thead tr th {
        background-color: #e2e8f0;
        color: #0f172a;
        font-weight: 700;
        border-bottom: 2px solid #94a3b8;
      }
      div[data-testid="stTable"] tbody tr:nth-child(odd) {
        background-color: #ffffff;
      }
      div[data-testid="stTable"] tbody tr:nth-child(even) {
        background-color: #f4f6f9;
      }
      div[data-testid="stTable"] tbody tr:hover {
        background-color: #e6f4f1;
      }
      /* Prominent styling for primary and nested tabs */
      button[data-baseweb="tab"] {
        font-weight: 600;
        font-size: 0.95rem;
        padding: 0.55rem 1.1rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

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
HEAT_OPTIONS = [1, 2, 3, 4]

SIGNATURE_ROLES = [
    ("referee", "Meet Referee"),
    ("starter", "Starter / Official"),
    ("home_coach", "Home Coach"),
    ("visitor_coach", "Visitor Coach"),
]


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

# Detect read-only Parent / Spectator mode via ?view=parents
raw_view_param = str(st.query_params.get("view", "")).strip().lower()
is_parent_view = raw_view_param in ("parents", "parent", "spectator", "readonly")

# Load active meet and persisted state from SQLite on every run
active_meet_id = get_active_meet_id()
all_meets = list_meets()
active_meet_meta = next((m for m in all_meets if m["meet_id"] == active_meet_id), None)
is_meet_closed = bool(active_meet_meta and active_meet_meta.get("status") == "CLOSED")

team_a_saved, team_b_saved = load_team_names(active_meet_id)
entries, results = load_all_data(active_meet_id)
rosters = load_rosters()
lineups = load_lineups(active_meet_id)
saved_signatures = load_meet_signatures(active_meet_id)


def _is_entry_exhibition(entry: Entry) -> bool:
    return bool(entry.is_exhibition) or (getattr(entry, "heat_number", 1) > 1)


def _pill_selector(
    label: str,
    options: list,
    key: str,
    format_func=None,
    default=None,
):
    """Uses st.segmented_control when available, falling back to horizontal st.radio."""
    if hasattr(st, "segmented_control"):
        return st.segmented_control(
            label,
            options=options,
            default=default if default is not None else options[0],
            format_func=format_func,
            key=key,
        )
    idx = options.index(default) if default in options else 0
    return st.radio(
        label,
        options=options,
        index=idx,
        format_func=format_func if format_func else str,
        horizontal=True,
        key=key,
    )


def _call_export_meet_html(
    team_a: str,
    team_b: str,
    div_totals: dict,
    gender: str,
    signatures: dict,
) -> str:
    """Calls export_meet_html and passes saved signatures when supported."""
    sig_params = inspect.signature(export_meet_html).parameters
    kwargs = {
        "team_a": team_a,
        "team_b": team_b,
        "div_totals": div_totals,
        "events": STANDARD_EVENTS,
        "entries": entries,
        "results": results,
        "gender": gender,
    }
    if "signatures" in sig_params:
        kwargs["signatures"] = signatures
    elif "saved_signatures" in sig_params:
        kwargs["saved_signatures"] = signatures
    return export_meet_html(**kwargs)


def render_signature_pad(role_key: str, role_label: str, existing_data_url: str = "") -> None:
    """Renders a touch/stylus/mouse HTML5 signature pad that generates a PNG data URL."""
    pad_html = f"""
    <div style="font-family: sans-serif; border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; background: #ffffff;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="font-size: 13px; font-weight: 600; color: #1e293b;">Draw Signature ({role_label})</span>
        <button type="button" id="clear_{role_key}" style="padding: 3px 10px; font-size: 12px; cursor: pointer; border: 1px solid #94a3b8; border-radius: 4px; background: #f8fafc;">Clear</button>
      </div>
      <canvas id="canvas_{role_key}" width="520" height="140" style="width: 100%; height: 140px; border: 1px dashed #64748b; border-radius: 6px; touch-action: none; background: #fcfcfd; cursor: crosshair;"></canvas>
      <div style="margin-top: 8px; display: flex; gap: 8px; align-items: center;">
        <button type="button" id="copy_{role_key}" style="padding: 5px 12px; font-size: 12px; font-weight: 600; cursor: pointer; border: none; border-radius: 4px; background: #0f766e; color: #ffffff;">Prepare Signature PNG</button>
        <span id="status_{role_key}" style="font-size: 12px; color: #475569;">Sign with stylus/pen, touch, or mouse, then click Prepare Signature PNG.</span>
      </div>
      <textarea id="out_{role_key}" rows="2" placeholder="Click 'Prepare Signature PNG' above or paste a PNG data URL..." style="width: 100%; margin-top: 6px; font-size: 11px; font-family: monospace; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px;">{existing_data_url}</textarea>
    </div>
    <script>
      (function() {{
        const canvas = document.getElementById("canvas_{role_key}");
        const ctx = canvas.getContext("2d");
        const clearBtn = document.getElementById("clear_{role_key}");
        const copyBtn = document.getElementById("copy_{role_key}");
        const statusEl = document.getElementById("status_{role_key}");
        const outEl = document.getElementById("out_{role_key}");

        function setupCanvas() {{
          const rect = canvas.getBoundingClientRect();
          const ratio = window.devicePixelRatio || 1;
          canvas.width = Math.max(300, Math.floor(rect.width * ratio));
          canvas.height = Math.max(110, Math.floor(rect.height * ratio));
          ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, rect.width, rect.height);
          ctx.strokeStyle = "#0f172a";
          ctx.lineWidth = 2.4;
          ctx.lineCap = "round";
          ctx.lineJoin = "round";
        }}

        setupCanvas();
        let drawing = false;
        let hasStrokes = false;
        let lastX = 0;
        let lastY = 0;

        function getPos(e) {{
          const rect = canvas.getBoundingClientRect();
          const clientX = e.touches && e.touches.length ? e.touches[0].clientX : e.clientX;
          const clientY = e.touches && e.touches.length ? e.touches[0].clientY : e.clientY;
          return {{
            x: clientX - rect.left,
            y: clientY - rect.top
          }};
        }}

        function startDraw(e) {{
          e.preventDefault();
          drawing = true;
          hasStrokes = true;
          const pos = getPos(e);
          lastX = pos.x;
          lastY = pos.y;
          ctx.beginPath();
          ctx.moveTo(lastX, lastY);
        }}

        function moveDraw(e) {{
          if (!drawing) return;
          e.preventDefault();
          const pos = getPos(e);
          ctx.lineTo(pos.x, pos.y);
          ctx.stroke();
          lastX = pos.x;
          lastY = pos.y;
        }}

        function endDraw(e) {{
          if (!drawing) return;
          e.preventDefault();
          drawing = false;
          ctx.closePath();
        }}

        canvas.addEventListener("pointerdown", startDraw);
        canvas.addEventListener("pointermove", moveDraw);
        window.addEventListener("pointerup", endDraw);

        clearBtn.addEventListener("click", function() {{
          setupCanvas();
          hasStrokes = false;
          outEl.value = "";
          statusEl.textContent = "Cleared pad.";
        }});

        copyBtn.addEventListener("click", function() {{
          if (!hasStrokes && !outEl.value.trim()) {{
            statusEl.textContent = "Please draw a signature first.";
            return;
          }}
          const dataUrl = canvas.toDataURL("image/png");
          outEl.value = dataUrl;
          outEl.select();
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(dataUrl).catch(function() {{}});
          }}
          statusEl.textContent = "PNG ready below (and copied if clipboard permitted). Paste into the Save Signature box and click Save Signature.";
        }});
      }})();
    </script>
    """
    components.html(pad_html, height=255)


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


def build_scoring_audit_rows(team_a: str, team_b: str, gender_filter: str) -> list[dict]:
    """Builds event-by-event points and running cumulative totals for officials verification."""
    running_a = 0.0
    running_b = 0.0
    audit_rows: list[dict] = []

    for ev in STANDARD_EVENTS:
        if gender_filter != "All" and ev.gender != gender_filter:
            continue

        ev_scores = score_event(
            event=ev,
            entries=entries,
            results=results,
            meet_format=MeetFormat.DUAL,
        )
        pts_a = float(ev_scores.get(team_a, 0.0))
        pts_b = float(ev_scores.get(team_b, 0.0))
        running_a += pts_a
        running_b += pts_b

        ev_entries = {e.entry_id: e for e in entries if e.event_number == ev.event_number}
        ev_results = [r for r in results if r.entry_id in ev_entries]
        place_counts = Counter(r.place for r in ev_results if r.place is not None)
        has_tie = any(cnt > 1 for cnt in place_counts.values())
        has_jd = any(r.manual_place is not None for r in ev_results)
        heat_nums = sorted({getattr(e, "heat_number", 1) for e in ev_entries.values()})

        notes: list[str] = []
        if len(heat_nums) > 1 or max(heat_nums, default=1) > 1:
            notes.append(f"Heats {','.join(str(h) for h in heat_nums)}")
        if has_tie:
            notes.append("Tie (Rule 7-1)")
        if has_jd:
            notes.append("JD Override")

        audit_rows.append(
            {
                "Event #": ev.event_number,
                "Division": "Girls" if ev.gender == "F" else "Boys",
                "Event": ev.name,
                f"{team_a} Pts": f"{pts_a:g}",
                f"{team_b} Pts": f"{pts_b:g}",
                f"{team_a} Running": f"{running_a:g}",
                f"{team_b} Running": f"{running_b:g}",
                "Scored Entries": len(ev_results),
                "Notes": ", ".join(notes) if notes else "—",
            }
        )

    return audit_rows


def render_leader_banner(
    label: str, score_a: float, score_b: float, name_a: str, name_b: str
) -> None:
    """Renders a compact highlight banner showing who currently leads a division."""
    if score_a > score_b:
        st.success(f"**{label} Leader:** {name_a} ({score_a:g} – {score_b:g})")
    elif score_b > score_a:
        st.success(f"**{label} Leader:** {name_b} ({score_b:g} – {score_a:g})")
    elif score_a > 0 or score_b > 0:
        st.info(f"**{label} Tied:** {score_a:g} – {score_b:g}")
    else:
        st.caption(f"{label}: No points scored yet")


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


# Score all events once so division totals and result places/points are up to date
div_totals = compute_division_totals(team_a_saved, team_b_saved)
g_score_a = div_totals["F"].get(team_a_saved, 0.0)
g_score_b = div_totals["F"].get(team_b_saved, 0.0)
b_score_a = div_totals["M"].get(team_a_saved, 0.0)
b_score_b = div_totals["M"].get(team_b_saved, 0.0)
meet_header_title = active_meet_meta["title"] if active_meet_meta else f"{team_a_saved} vs {team_b_saved}"


# ==============================================================================
# READ-ONLY PARENT / SPECTATOR VIEW (?view=parents)
# ==============================================================================
if is_parent_view:
    st.title(f"Live Meet Results & Times — {meet_header_title}")
    st.caption(
        "Spectator View (Read-Only): Live team scores, event results, and swimmer times."
    )

    p_top1, p_top2, p_top3 = st.columns([2.2, 2.0, 1.3], vertical_alignment="bottom")
    p_div = p_top1.radio(
        "Division", ["All", "Girls", "Boys"], horizontal=True, key="parent_div_filter"
    )
    p_search = p_top2.text_input(
        "Search Swimmer or Team",
        placeholder="Type a swimmer's name or team...",
        key="parent_search_input",
    ).strip().lower()
    p_auto_refresh = p_top3.checkbox("Auto-refresh (15s)", value=False, key="parent_autorefresh")

    s_cols = st.columns(4)
    s_cols[0].metric(
        f"Girls {team_a_saved}",
        f"{g_score_a:g}",
        delta="Leading" if g_score_a > g_score_b else None,
    )
    s_cols[1].metric(
        f"Girls {team_b_saved}",
        f"{g_score_b:g}",
        delta="Leading" if g_score_b > g_score_a else None,
    )
    s_cols[2].metric(
        f"Boys {team_a_saved}",
        f"{b_score_a:g}",
        delta="Leading" if b_score_a > b_score_b else None,
    )
    s_cols[3].metric(
        f"Boys {team_b_saved}",
        f"{b_score_b:g}",
        delta="Leading" if b_score_b > b_score_a else None,
    )

    results_by_entry_p = {r.entry_id: r for r in results}

    if p_search:
        st.divider()
        st.subheader(f"Matching Results for '{p_search}'")
        matched_rows: list[dict] = []
        for ev in STANDARD_EVENTS:
            if p_div == "Girls" and ev.gender != "F":
                continue
            if p_div == "Boys" and ev.gender != "M":
                continue

            ev_ents = [e for e in entries if e.event_number == ev.event_number]
            ev_ress = [
                results_by_entry_p[e.entry_id]
                for e in ev_ents
                if e.entry_id in results_by_entry_p
            ]
            place_counts = Counter(r.place for r in ev_ress if r.place is not None)
            tied_places = {p for p, cnt in place_counts.items() if cnt > 1}

            for ent in ev_ents:
                res = results_by_entry_p.get(ent.entry_id)
                if not res:
                    continue
                participants_str = (
                    f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
                    if ev.event_type == EventType.RELAY and ent.relay_letter
                    else ", ".join(ent.athlete_ids)
                )
                haystack = f"{ent.team_id} {participants_str}".lower()
                if p_search not in haystack:
                    continue

                if ev.event_type == EventType.DIVING and res.diving_score is not None:
                    perf = f"{res.diving_score:.2f}"
                elif res.official_time_cs is not None:
                    perf = format_cs_to_time(res.official_time_cs)
                else:
                    perf = "—"

                star = "*" if res.place in tied_places else ""
                place_txt = (
                    f"{res.place}{star} (JD)"
                    if res.place is not None and res.manual_place is not None
                    else (f"{res.place}{star}" if res.place is not None else "—")
                )
                heat_num = getattr(ent, "heat_number", 1)
                exh_flag = _is_entry_exhibition(ent)

                matched_rows.append(
                    {
                        "Event #": ev.event_number,
                        "Heat": f"H{heat_num}",
                        "Division": "Girls" if ev.gender == "F" else "Boys",
                        "Event": ev.name,
                        "Place": place_txt,
                        "Team": ent.team_id,
                        "Swimmer / Relay": participants_str,
                        "Time / Score": perf,
                        "Status": "" if res.status == ResultStatus.OK else res.status.value,
                        "Exh": "Exh" if exh_flag else "",
                        "Points": f"{res.points:g}",
                    }
                )

        if matched_rows:
            st.table(matched_rows)
        else:
            st.info("No recorded results matched your search in this division.")

    st.divider()
    st.subheader("Event-by-Event Results")

    any_event_shown = False
    for ev in STANDARD_EVENTS:
        if p_div == "Girls" and ev.gender != "F":
            continue
        if p_div == "Boys" and ev.gender != "M":
            continue

        ev_ents = [e for e in entries if e.event_number == ev.event_number]

        if p_search:
            filtered_pairs = []
            for ent in ev_ents:
                res = results_by_entry_p.get(ent.entry_id)
                if not res:
                    continue
                participants_str = (
                    f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
                    if ev.event_type == EventType.RELAY and ent.relay_letter
                    else ", ".join(ent.athlete_ids)
                )
                if p_search in f"{ent.team_id} {participants_str}".lower():
                    filtered_pairs.append((ent, res))
            if not filtered_pairs:
                continue
        else:
            filtered_pairs = [
                (ent, results_by_entry_p[ent.entry_id])
                for ent in ev_ents
                if ent.entry_id in results_by_entry_p
            ]

        any_event_shown = True
        g_lbl = "Girls" if ev.gender == "F" else "Boys"
        st.markdown(f"#### Event {ev.event_number}: {g_lbl} {ev.name}")

        if not filtered_pairs:
            st.caption("No results recorded yet.")
            continue

        filtered_pairs.sort(
            key=lambda pair: (
                getattr(pair[0], "heat_number", 1),
                pair[1].place is None,
                pair[1].place or 999,
            )
        )
        place_counts = Counter(r.place for _, r in filtered_pairs if r.place is not None)
        tied_places = {p for p, cnt in place_counts.items() if cnt > 1}

        ev_table_rows = []
        for ent, res in filtered_pairs:
            if ev.event_type == EventType.DIVING and res.diving_score is not None:
                perf = f"{res.diving_score:.2f}"
            elif res.official_time_cs is not None:
                perf = format_cs_to_time(res.official_time_cs)
            else:
                perf = "—"

            participants_str = (
                f"Relay {ent.relay_letter} ({', '.join(ent.athlete_ids)})"
                if ev.event_type == EventType.RELAY and ent.relay_letter
                else ", ".join(ent.athlete_ids)
            )
            star = "*" if res.place in tied_places else ""
            place_txt = (
                f"{res.place}{star} (JD)"
                if res.place is not None and res.manual_place is not None
                else (f"{res.place}{star}" if res.place is not None else "—")
            )
            heat_num = getattr(ent, "heat_number", 1)
            exh_flag = _is_entry_exhibition(ent)

            ev_table_rows.append(
                {
                    "Heat": f"H{heat_num}",
                    "Place": place_txt,
                    "Team": ent.team_id,
                    "Swimmer / Relay": participants_str,
                    "Time / Score": perf,
                    "Status": "" if res.status == ResultStatus.OK else res.status.value,
                    "Exh": "Exh" if exh_flag else "",
                    "Points": f"{res.points:g}",
                }
            )

        st.table(ev_table_rows)
        if tied_places:
            st.caption(
                "*Note: Per MIAA / NFHS Rule 7-1, tied place points are combined and divided equally."
            )

    if not any_event_shown:
        st.info("No matching events or results to display.")

    if p_auto_refresh:
        time.sleep(15)
        st.rerun()

    st.stop()


# ==============================================================================
# FULL OFFICIAL / TABLE WORKER WORKSPACE
# ==============================================================================
with st.sidebar:
    st.header("Saved Meets & Switcher")
    meet_ids = [m["meet_id"] for m in all_meets]
    meet_labels = {
        m["meet_id"]: (
            f"{m['title']} "
            f"[{'CLOSED' if m['status'] == 'CLOSED' else 'ACTIVE'}]"
        )
        for m in all_meets
    }
    current_idx = meet_ids.index(active_meet_id) if active_meet_id in meet_ids else 0
    picked_meet_id = st.selectbox(
        "Active / Saved Meet",
        options=meet_ids,
        index=current_idx,
        format_func=lambda mid: meet_labels.get(mid, mid),
        key="meet_switcher_select",
    )
    if picked_meet_id != active_meet_id:
        set_active_meet(picked_meet_id)
        for key in list(st.session_state.keys()):
            if key.startswith("lu_ev"):
                del st.session_state[key]
        st.rerun()

    if active_meet_meta:
        status_badge = "CLOSED (Archived)" if is_meet_closed else "ACTIVE"
        st.caption(
            f"Status: **{status_badge}** · Created: {active_meet_meta.get('created_at', '')}"
            + (
                f" · Closed: {active_meet_meta['closed_at']}"
                if active_meet_meta.get("closed_at")
                else ""
            )
        )

    c_close, _ = st.columns(2)
    if not is_meet_closed:
        if c_close.button("Close Meet", use_container_width=True):
            set_meet_status(active_meet_id, "CLOSED")
            st.rerun()
    else:
        if c_close.button("Reopen Meet", use_container_width=True):
            set_meet_status(active_meet_id, "ACTIVE")
            st.rerun()

    with st.expander("New / Save Meet"):
        with st.form("new_meet_form", clear_on_submit=True):
            new_title = st.text_input(
                "Meet Name",
                placeholder="e.g., Gardner vs Winchendon (Nov 23)",
            )
            new_team_a = st.text_input("Home Team (Even Lanes)", value=team_a_saved)
            new_team_b = st.text_input("Visitor Team (Odd Lanes)", value=team_b_saved)
            copy_lu = st.checkbox("Copy current lane lineups into new meet", value=False)
            if st.form_submit_button("Start New Meet", type="primary"):
                new_id = f"meet_{uuid.uuid4().hex[:8]}"
                create_new_meet(
                    meet_id=new_id,
                    title=new_title,
                    team_a=new_team_a,
                    team_b=new_team_b,
                    copy_lineups_from_current=copy_lu,
                )
                for key in list(st.session_state.keys()):
                    if key.startswith("lu_ev"):
                        del st.session_state[key]
                st.rerun()

        if active_meet_meta:
            with st.form("rename_meet_form"):
                renamed_title = st.text_input(
                    "Rename Current Meet",
                    value=active_meet_meta.get("title", ""),
                )
                if st.form_submit_button("Save Meet Name"):
                    rename_meet(active_meet_id, renamed_title)
                    st.rerun()

        if st.button("Delete Selected Meet", type="secondary"):
            delete_meet(active_meet_id)
            st.rerun()

    st.divider()
    st.header("Meet Setup")
    team_a = st.text_input(
        "Team A (Home - Even Lanes)",
        value=team_a_saved,
        disabled=is_meet_closed,
    )
    team_b = st.text_input(
        "Team B (Visitor - Odd Lanes)",
        value=team_b_saved,
        disabled=is_meet_closed,
    )
    if not is_meet_closed and (team_a, team_b) != (team_a_saved, team_b_saved):
        save_team_names(team_a, team_b, active_meet_id)

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
        st.caption("Add Missing Swimmer to Saved Roster")
        with st.form("quick_add_swimmer_form", clear_on_submit=True):
            qa_team = st.selectbox("Team", [team_a, team_b], key="qa_swimmer_team")
            qa_name = st.text_input("Swimmer Name", placeholder="Last, First")
            qa_gender = st.selectbox("Division / Gender", ["F", "M"], key="qa_swimmer_gender")
            if st.form_submit_button("Add Swimmer to Roster"):
                ok, msg = add_roster_swimmer(qa_team, qa_name, qa_gender)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    st.divider()
    st.header("Live Meet Scores")
    div_totals = compute_division_totals(team_a, team_b)

    g_score_a = div_totals["F"].get(team_a, 0.0)
    g_score_b = div_totals["F"].get(team_b, 0.0)
    b_score_a = div_totals["M"].get(team_a, 0.0)
    b_score_b = div_totals["M"].get(team_b, 0.0)

    st.subheader("Girls Division")
    g1, g2 = st.columns(2)
    g1.metric(
        team_a,
        f"{g_score_a:g}",
        delta="Leading" if g_score_a > g_score_b else None,
    )
    g2.metric(
        team_b,
        f"{g_score_b:g}",
        delta="Leading" if g_score_b > g_score_a else None,
    )
    render_leader_banner("Girls", g_score_a, g_score_b, team_a, team_b)

    st.subheader("Boys Division")
    b1, b2 = st.columns(2)
    b1.metric(
        team_a,
        f"{b_score_a:g}",
        delta="Leading" if b_score_a > b_score_b else None,
    )
    b2.metric(
        team_b,
        f"{b_score_b:g}",
        delta="Leading" if b_score_b > b_score_a else None,
    )
    render_leader_banner("Boys", b_score_a, b_score_b, team_a, team_b)

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

    st.caption("1-Page Official Report (HTML)")
    h1, h2 = st.columns(2)
    h1.download_button(
        label="Girls HTML",
        data=_call_export_meet_html(team_a, team_b, div_totals, "F", saved_signatures),
        file_name=f"girls_report_{safe_matchup}.html",
        mime="text/html",
        disabled=len(g_results) == 0,
        use_container_width=True,
    )
    h2.download_button(
        label="Boys HTML",
        data=_call_export_meet_html(team_a, team_b, div_totals, "M", saved_signatures),
        file_name=f"boys_report_{safe_matchup}.html",
        mime="text/html",
        disabled=len(b_results) == 0,
        use_container_width=True,
    )

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

    st.divider()
    st.subheader("Full Database Backup / Restore")
    st.download_button(
        label="Download Meet Backup (.json)",
        data=export_full_backup_json(),
        file_name=f"swim_meet_backup_{safe_matchup}.json",
        mime="application/json",
        use_container_width=True,
    )
    with st.expander("Restore Backup (.json)"):
        backup_file = st.file_uploader(
            "Select Backup JSON", type=["json"], key="backup_restore_uploader"
        )
        if backup_file is not None and st.button("Restore Database from Backup", type="secondary"):
            ok, msg = restore_full_backup_json(backup_file.getvalue().decode("utf-8"))
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    if st.button("Reset Current Meet", type="secondary", disabled=is_meet_closed):
        clear_all(active_meet_id)
        st.rerun()


st.title(f"MIAA / NFHS Dual Meet Scorer — {meet_header_title}")
if is_meet_closed:
    st.warning(
        "This meet is **CLOSED** (archived). You can view, print, or export results anytime, "
        "or click **Reopen Meet** in the sidebar to make edits."
    )

tab_scoring, tab_lineup, tab_audit, tab_signoff = st.tabs(
    [
        "⏱️ Event Scoring",
        "📋 Batch Lineup & Seeding",
        "📊 Official Scoring Check",
        "✍️ Official Sign-Off",
    ]
)


# ==============================================================================
# TAB 1: EVENT SCORING
# ==============================================================================
with tab_scoring:
    top_f1, top_f2 = st.columns([2.2, 2.8], vertical_alignment="bottom")
    with top_f1:
        division_filter = _pill_selector(
            "Division Filter",
            options=["All", "Girls", "Boys"],
            key="scoring_div_pill",
            default="All",
        ) or "All"

    filtered_events = [
        e
        for e in STANDARD_EVENTS
        if division_filter == "All"
        or (division_filter == "Girls" and e.gender == "F")
        or (division_filter == "Boys" and e.gender == "M")
    ]

    scored_event_nums = {
        e.event_number
        for e in entries
        if any(r.entry_id == e.entry_id for r in results)
    }

    event_labels = [
        f"Event {e.event_number}: {'Girls' if e.gender == 'F' else 'Boys'} {e.name}"
        f"{' ✓' if e.event_number in scored_event_nums else ''}"
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

    event_entries = {e.entry_id: e for e in entries if e.event_number == selected_event.event_number}
    event_results = [r for r in results if r.entry_id in event_entries]

    with top_f2:
        st.caption(
            f"**Active Event:** Event {selected_event.event_number} — {gender_label} {selected_event.name} "
            f"· **Recorded Entries:** {len(event_results)}"
        )

    # Focused sub-tabs inside Event Scoring so entry, results/editing, and athlete checks never crowd each other
    sc_sub_entry, sc_sub_results, sc_sub_lookup = st.tabs(
        [
            "⏱️ Enter Heat / Dive Results",
            f"🏆 Official Results & Edit ({len(event_results)})",
            "🔍 Swimmer Event Counts (3-2-1)",
        ]
    )

    # --- SUB-TAB 1A: RECORD HEAT / DIVING ---
    with sc_sub_entry:
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

                if st.form_submit_button("Record Dive Score", type="primary", disabled=is_meet_closed):
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
                            heat_number=1,
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
                            save_entry_and_result(new_entry, new_result, active_meet_id)
                            st.rerun()
        else:
            is_relay = selected_event.event_type == EventType.RELAY
            st.subheader(f"6-Lane Heat Entry — {gender_label} {selected_event.name}")

            selected_heat = _pill_selector(
                "Select Heat",
                options=HEAT_OPTIONS,
                format_func=lambda h: f"Heat {h} (Scoring)" if h == 1 else f"Heat {h} (Exhibition)",
                key=f"heat_num_ev_{selected_event.event_number}",
                default=1,
            ) or 1

            is_exh_heat = selected_heat > 1
            if is_exh_heat:
                st.info(
                    f"Heat {selected_heat} is an **Exhibition** heat: times and swimmer event counts are recorded, "
                    "but entries will not count toward team scoring."
                )
            else:
                st.caption(
                    "Pre-filled from Batch Lineup if saved. Leave unused lanes blank. "
                    "Use JD only for an official Judge's Decision place override."
                )

            with st.form(f"heat_grid_ev_{selected_event.event_number}_h{selected_heat}", clear_on_submit=True):
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
                    saved = lineups.get((selected_event.event_number, selected_heat, lane), {})
                    default_team_idx = 0 if lane % 2 == 0 else 1  # Even = Home, Odd = Visitor
                    if saved.get("team_id") in teams:
                        default_team_idx = teams.index(saved["team_id"])
                    default_team = teams[default_team_idx]
                    lane_roster = rosters.get((default_team, selected_event.gender), [])
                    saved_names = saved.get("athlete_ids", [])
                    key_prefix = f"ev{selected_event.event_number}_h{selected_heat}_l{lane}"

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
                            value=bool(saved.get("is_exhibition", False)) or is_exh_heat,
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
                            value=bool(saved.get("is_exhibition", False)) or is_exh_heat,
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
                            "exh": bool(l_exh) or is_exh_heat,
                            "malf": l_malf,
                        }
                    )

                override_limits = st.checkbox("Override NFHS entry limit warnings for this heat")
                submitted_heat = st.form_submit_button(
                    "Record Heat Results", type="primary", disabled=is_meet_closed
                )

                if submitted_heat:
                    pending_pairs: list[tuple[Entry, Result]] = []
                    parse_errors: list[str] = []

                    for row in lane_inputs:
                        athlete_list = row["names"]
                        if not athlete_list:
                            continue

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
                            is_exhibition=bool(row["exh"]) or is_exh_heat,
                            relay_letter=row["relay"].strip() if row["relay"] else None,
                            heat_number=selected_heat,
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
                                save_entry_and_result(ent, res, active_meet_id)
                            st.rerun()

    # --- SUB-TAB 1B: OFFICIAL RESULTS & EDIT ---
    with sc_sub_results:
        st.subheader(
            f"Official Results — Event {selected_event.event_number}: {gender_label} {selected_event.name}"
        )

        if not event_results:
            st.info("No results recorded for this event yet.")
        else:
            event_results.sort(
                key=lambda r: (
                    getattr(event_entries[r.entry_id], "heat_number", 1),
                    r.place is None,
                    r.place or 999,
                )
            )

            place_counts = Counter(r.place for r in event_results if r.place is not None)
            tied_places = {p for p, count in place_counts.items() if count > 1}

            rows = []
            for res in event_results:
                ent = event_entries[res.entry_id]
                heat_num = getattr(ent, "heat_number", 1)
                exh_flag = _is_entry_exhibition(ent)

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
                        "Heat": f"H{heat_num}",
                        "Place": place_display,
                        "Team": ent.team_id,
                        "Participant": participant_display,
                        "Official Time / Score": perf_display,
                        "Status": res.status.value,
                        "Exh": "Yes" if exh_flag else "",
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
                    f"H{getattr(event_entries[res.entry_id], 'heat_number', 1)} · "
                    f"{event_entries[res.entry_id].team_id} — "
                    f"{', '.join(event_entries[res.entry_id].athlete_ids)} "
                    f"(Place: {res.place if res.place is not None else '—'}"
                    f"{' JD' if res.manual_place is not None else ''})"
                )
                for res in event_results
            }
            results_by_id = {res.entry_id: res for res in event_results}

            st.divider()
            st.markdown("#### Edit Existing Result")
            edit_entry_id = st.selectbox(
                "Select Swimmer / Relay to Edit",
                options=list(result_options.keys()),
                format_func=lambda eid: result_options[eid],
                key=f"edit_res_select_ev_{selected_event.event_number}",
            )
            cur_entry = event_entries[edit_entry_id]
            cur_res = results_by_id[edit_entry_id]
            cur_heat = getattr(cur_entry, "heat_number", 1)
            cur_heat_idx = HEAT_OPTIONS.index(cur_heat) if cur_heat in HEAT_OPTIONS else 0
            teams_list = [team_a, team_b]
            cur_team_idx = teams_list.index(cur_entry.team_id) if cur_entry.team_id in teams_list else 0
            status_list = [s.value for s in ResultStatus]
            cur_status_idx = (
                status_list.index(cur_res.status.value)
                if cur_res.status.value in status_list
                else 0
            )
            cur_jd_idx = (
                JD_OPTIONS.index(cur_res.manual_place)
                if cur_res.manual_place in JD_OPTIONS
                else 0
            )
            edit_roster = rosters.get((cur_entry.team_id, selected_event.gender), [])

            with st.form(f"edit_res_form_ev_{selected_event.event_number}_{edit_entry_id}"):
                f1, f2, f3, f4 = st.columns([1.3, 2.0, 0.85, 0.85])
                upd_team = f1.selectbox("Team", teams_list, index=cur_team_idx)
                upd_heat = f3.selectbox(
                    "Heat",
                    options=HEAT_OPTIONS,
                    index=cur_heat_idx,
                    format_func=lambda h: f"Heat {h}",
                )

                if selected_event.event_type == EventType.RELAY:
                    if edit_roster:
                        upd_athletes = f2.multiselect(
                            "Relay Swimmers",
                            options=edit_roster,
                            default=[n for n in cur_entry.athlete_ids if n in edit_roster],
                            max_selections=4,
                        )
                    else:
                        raw_upd_rly = f2.text_input(
                            "Relay Swimmers (comma-sep)",
                            value=", ".join(cur_entry.athlete_ids),
                        )
                        upd_athletes = [n.strip() for n in raw_upd_rly.split(",") if n.strip()]
                    upd_relay = f4.text_input(
                        "Relay Letter",
                        value=cur_entry.relay_letter or "A",
                    )
                else:
                    upd_relay = None
                    cur_single = cur_entry.athlete_ids[0] if cur_entry.athlete_ids else ""
                    if edit_roster:
                        opts = [""] + edit_roster
                        picked_idx = opts.index(cur_single) if cur_single in opts else 0
                        picked_ath = f2.selectbox("Athlete", options=opts, index=picked_idx)
                        upd_athletes = [picked_ath] if picked_ath else []
                    else:
                        raw_upd_ath = f2.text_input("Athlete Name", value=cur_single)
                        upd_athletes = [raw_upd_ath.strip()] if raw_upd_ath.strip() else []
                    f4.caption("Ind / Dive")

                if selected_event.event_type == EventType.DIVING:
                    p1, p2, p3, p4 = st.columns([1.5, 1.2, 1.0, 1.3])
                    upd_dive = p1.number_input(
                        "Total Score",
                        min_value=0.0,
                        step=0.05,
                        format="%.2f",
                        value=float(cur_res.diving_score or 0.0),
                    )
                    upd_status = p2.selectbox("Status", status_list, index=cur_status_idx)
                    upd_jd = p3.selectbox("JD Place", JD_OPTIONS, index=cur_jd_idx)
                    upd_exh = p4.checkbox("Exhibition", value=cur_entry.is_exhibition)
                    upd_watch_str = ""
                    upd_bkp_str = ""
                    upd_malf = False
                else:
                    t1, t2, t3 = st.columns([1.3, 1.7, 1.0])
                    upd_watch_str = t1.text_input(
                        "Watch Time",
                        value=(
                            format_cs_to_time(cur_res.watch_time_cs)
                            if cur_res.watch_time_cs is not None
                            else ""
                        ),
                        placeholder="24.51 or 1:45.20",
                    )
                    upd_bkp_str = t2.text_input(
                        "Backups (csv)",
                        value=", ".join(format_cs_to_time(t) for t in cur_res.backup_times_cs),
                        placeholder="24.51, 24.52",
                    )
                    upd_malf = t3.checkbox(
                        "Watch Malfunction",
                        value=(
                            cur_res.watch_time_cs is not None
                            and cur_res.official_time_cs is not None
                            and cur_res.official_time_cs != cur_res.watch_time_cs
                        ),
                    )

                    s1, s2, s3 = st.columns([1.3, 1.2, 1.5])
                    upd_status = s1.selectbox("Status", status_list, index=cur_status_idx)
                    upd_jd = s2.selectbox("JD Place", JD_OPTIONS, index=cur_jd_idx)
                    upd_exh = s3.checkbox(
                        "Exhibition", value=bool(cur_entry.is_exhibition) or (upd_heat > 1)
                    )
                    upd_dive = None

                upd_note = st.text_input(
                    "Official / JD Note (optional)",
                    value=cur_res.override_note,
                    placeholder="e.g., Corrected watch time / JD place",
                )
                upd_override_limits = st.checkbox(
                    "Override NFHS entry limit warnings",
                    key=f"upd_ovr_lim_{selected_event.event_number}_{edit_entry_id}",
                )

                if st.form_submit_button("Save Result Changes", type="primary", disabled=is_meet_closed):
                    if not upd_athletes:
                        st.error("Please enter at least one athlete.")
                    else:
                        parse_ok = True
                        upd_watch_cs = None
                        upd_backups_cs: list[int] = []
                        upd_official_cs = None

                        if selected_event.event_type != EventType.DIVING:
                            try:
                                upd_watch_cs = (
                                    parse_time_to_cs(upd_watch_str)
                                    if upd_watch_str.strip()
                                    else None
                                )
                                upd_backups_cs = [
                                    parse_time_to_cs(t)
                                    for t in upd_bkp_str.split(",")
                                    if t.strip()
                                ]
                            except ValueError:
                                st.error("Invalid time format. Use SS.cc or MM:SS.cc.")
                                parse_ok = False
                            else:
                                upd_official_cs = calculate_official_time(
                                    upd_watch_cs, upd_backups_cs, upd_malf
                                )

                        if parse_ok:
                            updated_entry = Entry(
                                entry_id=cur_entry.entry_id,
                                event_number=cur_entry.event_number,
                                team_id=upd_team,
                                athlete_ids=upd_athletes,
                                is_exhibition=bool(upd_exh) or (int(upd_heat) > 1),
                                relay_letter=(
                                    upd_relay.strip() if upd_relay else None
                                ),
                                heat_number=int(upd_heat),
                            )
                            other_entries = [
                                e for e in entries if e.entry_id != cur_entry.entry_id
                            ]
                            projected_entries = other_entries + [updated_entry]
                            violations: list[str] = []
                            for ath_id in upd_athletes:
                                violations.extend(
                                    validate_athlete_entries(
                                        ath_id, projected_entries, EVENTS_BY_NUM
                                    )
                                )

                            if violations and not upd_override_limits:
                                for msg in violations:
                                    st.warning(f"NFHS Rule 3-2-1 Violation: {msg}")
                                st.error(
                                    "Update blocked. Fix the lineup or check 'Override NFHS entry limit warnings'."
                                )
                            else:
                                updated_result = Result(
                                    entry_id=cur_res.entry_id,
                                    watch_time_cs=upd_watch_cs,
                                    backup_times_cs=upd_backups_cs,
                                    diving_score=(
                                        float(upd_dive)
                                        if selected_event.event_type == EventType.DIVING
                                        and upd_dive is not None
                                        else None
                                    ),
                                    status=ResultStatus(upd_status),
                                    official_time_cs=upd_official_cs,
                                    manual_place=(
                                        None if upd_jd == "Auto" else int(upd_jd)
                                    ),
                                    override_note=upd_note,
                                )
                                update_entry_and_result(updated_entry, updated_result)
                                st.rerun()

            st.divider()
            if st.button(f"Clear Event {selected_event.event_number} Results", disabled=is_meet_closed):
                clear_event(selected_event.event_number, active_meet_id)
                st.rerun()

    # --- SUB-TAB 1C: SWIMMER EVENT COUNT LOOKUP ---
    with sc_sub_lookup:
        st.subheader("Swimmer Event Count Lookup (NFHS Rule 3-2-1)")
        st.caption("Check total events (max 4) and individual/diving events (max 2) before deck changes.")
        usage_rows = get_athlete_usage()
        if not usage_rows:
            st.info("No athletes recorded in this meet yet.")
        else:
            swimmer_filter_q = (
                st.text_input(
                    "Filter athlete",
                    placeholder="Type swimmer name...",
                    key=f"swimmer_lookup_q_{selected_event.event_number}",
                )
                .strip()
                .lower()
            )
            shown_usage = [
                u for u in usage_rows if not swimmer_filter_q or swimmer_filter_q in u["Athlete"].lower()
            ]
            if shown_usage:
                st.table(shown_usage)
            else:
                st.caption("No matching athletes found.")


# ==============================================================================
# TAB 2: BATCH LINEUP & SEEDING
# ==============================================================================
with tab_lineup:
    populated_lane_count = sum(1 for d in lineups.values() if d.get("athlete_ids"))

    lu_h1, lu_h2 = st.columns([3.2, 1.3], vertical_alignment="center")
    lu_h1.subheader("Batch Lineup & Seeding")
    lu_h2.metric("Seeded Lanes", f"{populated_lane_count}")

    st.caption(
        "Assign swimmers and lanes across multiple heats per swimming event. "
        "Heat 1 is the scoring heat; Heat 2+ are automatically marked Exhibition. "
        "Saved lineups pre-fill Event Scoring and print on Heat Sheets and Lane Timer Sheets."
    )

    # Focused sub-tabs separating Lineup Entry from Printable Deck Sheets
    lu_sub_seeding, lu_sub_prints = st.tabs(
        [
            "🏊 Lineup & Heat Seeding",
            "🖨️ Printable Heat & Timer Sheets",
        ]
    )

    # --- SUB-TAB 2A: LINEUP & HEAT SEEDING ---
    with lu_sub_seeding:
        lineup_div = _pill_selector(
            "Show Division",
            options=["All", "Girls", "Boys"],
            key="lineup_div_pill",
            default="All",
        ) or "All"

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

                saved_heats = [
                    h
                    for (ev_num, h, _l), d in lineups.items()
                    if ev_num == ev.event_number and d.get("athlete_ids")
                ]
                seeded_in_event = sum(
                    1
                    for (ev_num, _h, _l), d in lineups.items()
                    if ev_num == ev.event_number and d.get("athlete_ids")
                )
                default_heat_count = max(saved_heats) if saved_heats else 1
                hc_key = f"lu_heat_count_ev{ev.event_number}"
                if hc_key not in st.session_state:
                    st.session_state[hc_key] = default_heat_count

                badge_txt = f" · {seeded_in_event} seeded" if seeded_in_event else ""
                with st.expander(
                    f"Event {ev.event_number}: {g_label} {ev.name} "
                    f"({st.session_state[hc_key]} Heat{'s' if st.session_state[hc_key] > 1 else ''}{badge_txt})",
                    expanded=st.session_state[hc_key] > 1,
                ):
                    num_heats = st.selectbox(
                        "Number of Heats to Seed",
                        options=HEAT_OPTIONS,
                        key=hc_key,
                        format_func=lambda n: f"{n} Heat" if n == 1 else f"{n} Heats (Heat 2+ Exhibition)",
                    )

                    for heat_num in range(1, num_heats + 1):
                        heat_label = (
                            f"Heat {heat_num} (Scoring)"
                            if heat_num == 1
                            else f"Heat {heat_num} (Exhibition)"
                        )
                        st.markdown(f"**{heat_label}**")

                        for lane in range(1, 7):
                            saved = lineups.get((ev.event_number, heat_num, lane), {})
                            default_team_idx = 0 if lane % 2 == 0 else 1
                            if saved.get("team_id") in teams:
                                default_team_idx = teams.index(saved["team_id"])

                            if is_rly:
                                c_lane, c_team, c_rly, c_swimmer, c_exh = st.columns(
                                    [0.5, 1.3, 0.55, 2.7, 0.55]
                                )
                            else:
                                c_lane, c_team, c_swimmer, c_exh = st.columns([0.5, 1.4, 3.1, 0.6])

                            c_lane.markdown(f"**L{lane}**")

                            l_team = c_team.selectbox(
                                "Team",
                                teams,
                                index=default_team_idx,
                                key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_team",
                                label_visibility="collapsed",
                            )
                            lane_roster = rosters.get((l_team, ev.gender), [])
                            saved_names = saved.get("athlete_ids", [])

                            if is_rly:
                                l_relay = c_rly.text_input(
                                    "Rly",
                                    value=saved.get("relay_letter") or "A",
                                    key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_rly",
                                    label_visibility="collapsed",
                                )
                                if lane_roster:
                                    l_names = c_swimmer.multiselect(
                                        "Swimmers",
                                        options=lane_roster,
                                        default=[n for n in saved_names if n in lane_roster],
                                        max_selections=4,
                                        placeholder="Select 4 swimmers...",
                                        key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_names",
                                        label_visibility="collapsed",
                                    )
                                else:
                                    raw_rly = c_swimmer.text_input(
                                        "Swimmers",
                                        value=", ".join(saved_names),
                                        placeholder="Smith, Jones, Lee, Patel",
                                        key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_names",
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
                                        key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_names",
                                        label_visibility="collapsed",
                                    )
                                    l_names = [picked] if picked else []
                                else:
                                    raw_ind = c_swimmer.text_input(
                                        "Swimmer",
                                        value=saved_names[0] if saved_names else "",
                                        placeholder="Last, First",
                                        key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_names",
                                        label_visibility="collapsed",
                                    )
                                    l_names = [raw_ind.strip()] if raw_ind.strip() else []

                            l_exh = c_exh.checkbox(
                                "Exh",
                                value=bool(saved.get("is_exhibition", False)) or (heat_num > 1),
                                key=f"lu_ev{ev.event_number}_h{heat_num}_l{lane}_exh",
                                label_visibility="collapsed",
                            )

                            pending_lineups.append(
                                {
                                    "event_number": ev.event_number,
                                    "heat_number": heat_num,
                                    "lane": lane,
                                    "team_id": l_team,
                                    "athlete_ids": l_names,
                                    "relay_letter": l_relay.strip() if l_relay else None,
                                    "is_exhibition": bool(l_exh) or (heat_num > 1),
                                }
                            )

                    for extra_heat in range(num_heats + 1, max(HEAT_OPTIONS) + 1):
                        for lane in range(1, 7):
                            pending_lineups.append(
                                {
                                    "event_number": ev.event_number,
                                    "heat_number": extra_heat,
                                    "lane": lane,
                                    "team_id": team_a,
                                    "athlete_ids": [],
                                    "relay_letter": None,
                                    "is_exhibition": True,
                                }
                            )

            override_lineup_limits = st.checkbox(
                "Override NFHS entry limit warnings for this lineup"
            )
            submitted_lineups = st.form_submit_button(
                "Save All Lineups", type="primary", disabled=is_meet_closed
            )

            if submitted_lineups:
                merged_lineups = dict(lineups)
                for row in pending_lineups:
                    key = (row["event_number"], row["heat_number"], row["lane"])
                    if row["athlete_ids"]:
                        merged_lineups[key] = row
                    else:
                        merged_lineups.pop(key, None)

                projected_lineup_entries = [
                    Entry(
                        entry_id=f"lu_{ev_num}_h{h_num}_{lane}",
                        event_number=ev_num,
                        team_id=data["team_id"],
                        athlete_ids=data["athlete_ids"],
                        is_exhibition=bool(data.get("is_exhibition", False)) or (h_num > 1),
                        relay_letter=data.get("relay_letter"),
                        heat_number=h_num,
                    )
                    for (ev_num, h_num, lane), data in merged_lineups.items()
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
                    save_lineups(pending_lineups, active_meet_id)
                    st.success("Lineups saved and synced to Event Scoring.")
                    st.rerun()

        st.divider()
        if st.button(
            "Clear All Lineups",
            type="secondary",
            disabled=len(lineups) == 0 or is_meet_closed,
            help="Clears all saved lane assignments across all events. Rosters and recorded results are not affected.",
        ):
            clear_lineups(active_meet_id)
            for key in list(st.session_state.keys()):
                if key.startswith("lu_"):
                    del st.session_state[key]
            st.rerun()

    # --- SUB-TAB 2B: PRINTABLE HEAT & TIMER SHEETS ---
    with lu_sub_prints:
        st.subheader("Printable Deck Reports & Lane Timer Sheets")
        st.caption(
            "Download print-ready HTML sheets formatted for clipboards, lane timers, and spectator posting."
        )

        heat_sheet_html = export_heat_sheet_html(
            team_a=team_a,
            team_b=team_b,
            events=STANDARD_EVENTS,
            lineups=lineups,
        )
        timer_sheets_html = export_lane_timer_sheets_html(
            team_a=team_a,
            team_b=team_b,
            events=STANDARD_EVENTS,
            lineups=lineups,
        )

        opt_col1, opt_col2 = st.columns(2)
        only_populated_cards = opt_col1.checkbox(
            "Only print Event Timer Cards for events with lineups or results",
            value=False,
            key="only_populated_timer_cards",
        )
        only_populated_lane_pairs = opt_col2.checkbox(
            "Only print Lane Event-Pair Sheets for populated event pairs",
            value=False,
            key="only_populated_lane_pair_sheets",
        )

        pair_timer_sheets_html = export_event_pair_timer_sheets_html(
            team_a=team_a,
            team_b=team_b,
            events=STANDARD_EVENTS,
            lineups=lineups,
            only_populated=only_populated_cards,
            entries=entries,
            results=results,
        )
        lane_pair_sheets_html = export_lane_event_pair_sheets_html(
            team_a=team_a,
            team_b=team_b,
            events=STANDARD_EVENTS,
            lineups=lineups,
            only_populated=only_populated_lane_pairs,
            entries=entries,
            results=results,
        )

        rep_c1, rep_c2 = st.columns(2)
        with rep_c1:
            st.markdown("**Heat Sheet (All Seeded Events)**")
            st.caption("Master heat-by-heat and lane-by-lane sheet for coaches and officials.")
            st.download_button(
                label="Download Heat Sheet (HTML)",
                data=heat_sheet_html,
                file_name=f"heat_sheet_{team_a}_vs_{team_b}.html".replace(" ", "_"),
                mime="text/html",
                disabled=len(lineups) == 0,
                use_container_width=True,
            )

            st.markdown("**Event Timer Cards (Girls / Boys Pairs)**")
            st.caption("Paired Girls/Boys event cards for clipboards.")
            st.download_button(
                label="Download Event Timer Cards (G/B)",
                data=pair_timer_sheets_html,
                file_name=f"event_timer_cards_{team_a}_vs_{team_b}.html".replace(" ", "_"),
                mime="text/html",
                use_container_width=True,
            )

        with rep_c2:
            st.markdown("**Lane Timer Sheets (By Lane)**")
            st.caption("Standard lane-by-lane timer sheets across the meet.")
            st.download_button(
                label="Download Lane Timer Sheets (HTML)",
                data=timer_sheets_html,
                file_name=f"lane_timer_sheets_{team_a}_vs_{team_b}.html".replace(" ", "_"),
                mime="text/html",
                use_container_width=True,
            )

            st.markdown("**Lane Event-Pair Sheets (1 Page/Lane, Ev 1–24)**")
            st.caption("Single-page per lane sheet pairing consecutive Girls & Boys events.")
            st.download_button(
                label="Download Lane Event-Pair Sheets (HTML)",
                data=lane_pair_sheets_html,
                file_name=f"lane_event_pair_sheets_{team_a}_vs_{team_b}.html".replace(" ", "_"),
                mime="text/html",
                use_container_width=True,
            )


# ==============================================================================
# TAB 3: OFFICIAL SCORING CHECK (AUDIT VIEW)
# ==============================================================================
with tab_audit:
    st.subheader("Official Scoring Audit & Running Totals")
    st.caption(
        "Central verification view for meet officials and coaches to confirm event-by-event "
        "points, running cumulative totals, ties, and Judge's Decision (JD) overrides."
    )

    a_filter_col, a_expand_col = st.columns([2.5, 1.5], vertical_alignment="bottom")
    audit_div = _pill_selector(
        "Division View",
        options=["All", "Girls", "Boys"],
        key="audit_div_pill",
        default="All",
    ) or "All"
    expand_all_events = a_expand_col.checkbox("Expand all event point breakdowns", value=False)

    gender_code = "F" if audit_div == "Girls" else ("M" if audit_div == "Boys" else "All")

    s_cols = st.columns(4)
    s_cols[0].metric(f"Girls {team_a}", f"{g_score_a:g}")
    s_cols[1].metric(f"Girls {team_b}", f"{g_score_b:g}")
    s_cols[2].metric(f"Boys {team_a}", f"{b_score_a:g}")
    s_cols[3].metric(f"Boys {team_b}", f"{b_score_b:g}")

    audit_rows = build_scoring_audit_rows(team_a, team_b, gender_code)
    st.dataframe(audit_rows, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Event-by-Event Point Breakdown")

    entries_by_id_all = {e.entry_id: e for e in entries}
    for ev in STANDARD_EVENTS:
        if gender_code != "All" and ev.gender != gender_code:
            continue

        ev_scores = score_event(
            event=ev,
            entries=entries,
            results=results,
            meet_format=MeetFormat.DUAL,
        )
        ev_pts_a = float(ev_scores.get(team_a, 0.0))
        ev_pts_b = float(ev_scores.get(team_b, 0.0))
        ev_res_list = [
            r
            for r in results
            if entries_by_id_all.get(r.entry_id)
            and entries_by_id_all[r.entry_id].event_number == ev.event_number
        ]
        ev_res_list.sort(
            key=lambda r: (
                getattr(entries_by_id_all[r.entry_id], "heat_number", 1),
                r.place is None,
                r.place or 999,
            )
        )
        g_lbl = "Girls" if ev.gender == "F" else "Boys"

        with st.expander(
            f"Event {ev.event_number}: {g_lbl} {ev.name} — {team_a}: {ev_pts_a:g} | {team_b}: {ev_pts_b:g}",
            expanded=expand_all_events,
        ):
            if not ev_res_list:
                st.caption("No results recorded yet.")
            else:
                detail_rows = []
                for r in ev_res_list:
                    ent = entries_by_id_all[r.entry_id]
                    heat_num = getattr(ent, "heat_number", 1)
                    exh_flag = _is_entry_exhibition(ent)
                    perf = (
                        f"{r.diving_score:.2f}"
                        if ev.event_type == EventType.DIVING and r.diving_score is not None
                        else (
                            format_cs_to_time(r.official_time_cs)
                            if r.official_time_cs is not None
                            else "—"
                        )
                    )
                    detail_rows.append(
                        {
                            "Heat": f"H{heat_num}",
                            "Place": (
                                f"{r.place} (JD)"
                                if r.place is not None and r.manual_place is not None
                                else (str(r.place) if r.place is not None else "—")
                            ),
                            "Team": ent.team_id,
                            "Participant": ", ".join(ent.athlete_ids),
                            "Time / Score": perf,
                            "Status": r.status.value,
                            "Exh": "Yes" if exh_flag else "",
                            "Points": f"{r.points:g}",
                            "Note": r.override_note or "—",
                        }
                    )
                st.table(detail_rows)


# ==============================================================================
# TAB 4: OFFICIAL SIGN-OFF (ELECTRONIC SIGNATURE CAPTURE)
# ==============================================================================
with tab_signoff:
    st.subheader("Electronic Official & Coach Sign-Off")
    st.caption(
        "Draw a signature using a stylus/pen, touch screen, or mouse, click **Prepare Signature PNG**, "
        "ensure the PNG data URL is in the form field below, enter the signer's name, and click **Save Signature**."
    )

    role_keys = [r[0] for r in SIGNATURE_ROLES]
    role_names = {r[0]: r[1] for r in SIGNATURE_ROLES}

    picked_role = st.selectbox(
        "Signer Role",
        options=role_keys,
        format_func=lambda rk: role_names[rk],
        key="signoff_role_select",
    )
    existing_sig = saved_signatures.get(picked_role, {})

    render_signature_pad(
        role_key=picked_role,
        role_label=role_names[picked_role],
        existing_data_url=existing_sig.get("signature_data_url", ""),
    )

    with st.form(f"save_sig_form_{picked_role}"):
        signer_name_input = st.text_input(
            "Printed Name",
            value=existing_sig.get("signer_name", ""),
            placeholder=f"e.g., {role_names[picked_role]} Name",
        )
        sig_data_url_input = st.text_area(
            "Signature PNG Data URL (paste or confirm after clicking 'Prepare Signature PNG')",
            value=existing_sig.get("signature_data_url", ""),
            height=75,
        )
        s_col1, s_col2 = st.columns([1, 1])
        save_sig_clicked = s_col1.form_submit_button(
            "Save Signature", type="primary", disabled=is_meet_closed
        )
        clear_sig_clicked = s_col2.form_submit_button(
            "Remove Saved Signature", type="secondary", disabled=is_meet_closed
        )

        if save_sig_clicked:
            if not sig_data_url_input.strip().startswith("data:image/"):
                st.error(
                    "Please draw a signature and click 'Prepare Signature PNG' (or paste a valid image data URL) before saving."
                )
            else:
                save_meet_signature(
                    meet_id=active_meet_id,
                    role_key=picked_role,
                    signer_name=signer_name_input,
                    signature_data_url=sig_data_url_input,
                )
                st.success(f"Saved signature for {role_names[picked_role]}.")
                st.rerun()

        if clear_sig_clicked:
            delete_meet_signature(active_meet_id, picked_role)
            st.rerun()

    st.divider()
    st.subheader("Recorded Meet Sign-Offs")
    sig_grid = st.columns(2)
    for idx, (rk, r_label) in enumerate(SIGNATURE_ROLES):
        with sig_grid[idx % 2]:
            rec = saved_signatures.get(rk)
            st.markdown(f"**{r_label}**")
            if rec and rec.get("signature_data_url"):
                st.image(rec["signature_data_url"], width=280)
                who = rec.get("signer_name") or "Name not entered"
                st.caption(f"Signed by: **{who}** · {rec.get('signed_at', '')}")
            else:
                st.caption("No signature recorded yet.")
