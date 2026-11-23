from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import combinations, groupby
from typing import Optional

from models import Entry, Event, EventType, Result, ResultStatus


class MeetFormat(Enum):
    DUAL = "DUAL"
    CHAMPIONSHIP = "CHAMPIONSHIP"


@dataclass(frozen=True)
class ScoringConfig:
    individual_points: tuple[int, ...]
    relay_points: tuple[int, ...]
    max_ind_scorers_per_team: int
    max_relay_scorers_per_team: int


SCORING_CONFIGS: dict[MeetFormat, ScoringConfig] = {
    MeetFormat.DUAL: ScoringConfig(
        individual_points=(6, 4, 3, 2, 1),
        relay_points=(8, 4, 2),
        max_ind_scorers_per_team=3,
        max_relay_scorers_per_team=2,
    ),
    MeetFormat.CHAMPIONSHIP: ScoringConfig(
        individual_points=(20, 17, 16, 15, 14, 13, 12, 11, 9, 7, 6, 5, 4, 3, 2, 1),
        relay_points=(40, 34, 32, 30, 28, 26, 24, 22, 18, 14, 12, 10, 8, 6, 4, 2),
        max_ind_scorers_per_team=4,
        max_relay_scorers_per_team=1,
    ),
}


def _performance_key(result: Result, event_type: EventType) -> Optional[float]:
    """Returns the comparable metric for ranking, or None if missing."""
    if event_type == EventType.DIVING:
        return result.diving_score
    return result.official_time_cs


def _rank_into_groups(
    eligible: list[tuple[Entry, Result]],
    event_type: EventType,
) -> list[list[tuple[Entry, Result]]]:
    """
    Orders eligible (Entry, Result) pairs into finish groups (supporting ties).
    Results with a valid `manual_place` (Judge's Decision) are pinned to their
    official slot; remaining results fill open slots by performance.
    """
    is_diving = event_type == EventType.DIVING
    pinned_by_place: dict[int, list[tuple[Entry, Result]]] = defaultdict(list)
    unpinned: list[tuple[Entry, Result]] = []

    for entry, res in eligible:
        if res.manual_place is not None and res.manual_place >= 1:
            pinned_by_place[res.manual_place].append((entry, res))
        else:
            unpinned.append((entry, res))

    # Sort unpinned entries by performance and group exact ties
    unpinned.sort(
        key=lambda pair: _performance_key(pair[1], event_type),  # type: ignore[arg-type]
        reverse=is_diving,
    )
    unpinned_groups: list[list[tuple[Entry, Result]]] = [
        list(group_iter)
        for _, group_iter in groupby(
            unpinned, key=lambda pair: _performance_key(pair[1], event_type)
        )
    ]

    # Merge pinned slots and unpinned groups in finish order
    ranked_groups: list[list[tuple[Entry, Result]]] = []
    current_slot = 1

    while pinned_by_place or unpinned_groups:
        due_pinned = [p for p in pinned_by_place if p <= current_slot]
        if due_pinned:
            p = min(due_pinned)
            group = pinned_by_place.pop(p)
        elif unpinned_groups:
            group = unpinned_groups.pop(0)
        else:
            p = min(pinned_by_place)
            group = pinned_by_place.pop(p)

        ranked_groups.append(group)
        current_slot += len(group)

    return ranked_groups


def score_event(
    event: Event,
    entries: list[Entry],
    results: list[Result],
    meet_format: MeetFormat = MeetFormat.DUAL,
    team_filter: Optional[set[str]] = None,
) -> dict[str, float]:
    """
    Scores a single event according to MIAA/NFHS rules, honoring official
    manual_place (Judge's Decision) overrides when present.

    - Updates `place` and `points` on each Result object in place.
    - Returns a dict mapping `team_id` -> total points earned in this event.
    - Pass `team_filter` (e.g., {"TEAM_A", "TEAM_B"}) to score head-to-head
      in a double-dual or triple-dual meet.
    """
    config = SCORING_CONFIGS[meet_format]
    is_relay = event.event_type == EventType.RELAY

    points_table = config.relay_points if is_relay else config.individual_points
    max_per_team = (
        config.max_relay_scorers_per_team
        if is_relay
        else config.max_ind_scorers_per_team
    )

    entries_by_id = {e.entry_id: e for e in entries if e.event_number == event.event_number}

    # 1. Reset previous places/points and filter to valid, scoring-eligible results
    eligible: list[tuple[Entry, Result]] = []
    for res in results:
        entry = entries_by_id.get(res.entry_id)
        if entry is None:
            continue

        res.place = None
        res.points = 0.0

        if team_filter and entry.team_id not in team_filter:
            continue
        if res.status != ResultStatus.OK or entry.is_exhibition:
            continue
        if _performance_key(res, event.event_type) is None and res.manual_place is None:
            continue

        eligible.append((entry, res))

    # 2. Rank into finish groups (honoring manual_place overrides and time/score ties)
    ranked_groups = _rank_into_groups(eligible, event.event_type)

    # 3. Enforce per-team scoring caps (e.g., max 2 relays per team in a dual meet)
    team_counts: dict[str, int] = defaultdict(int)
    scoring_groups: list[list[tuple[Entry, Result]]] = []

    for group in ranked_groups:
        kept: list[tuple[Entry, Result]] = []
        for entry, res in group:
            if team_counts[entry.team_id] < max_per_team:
                kept.append((entry, res))
                team_counts[entry.team_id] += 1
        if kept:
            scoring_groups.append(kept)

    # 4. Assign places and split points for ties
    team_scores: dict[str, float] = defaultdict(float)
    current_idx = 0  # 0-based index into points_table

    for tied_group in scoring_groups:
        k = len(tied_group)
        place = current_idx + 1

        # Slice the points for all positions occupied by the tie
        available_points = points_table[current_idx : current_idx + k]
        shared_points = sum(available_points) / k if available_points else 0.0

        for entry, res in tied_group:
            res.place = place
            res.points = shared_points
            team_scores[entry.team_id] += shared_points

        current_idx += k

    return dict(team_scores)


def score_head_to_head_meet(
    events: list[Event],
    entries: list[Entry],
    results: list[Result],
    team_ids: list[str],
) -> dict[tuple[str, str], dict[str, float]]:
    """
    Scores a dual, double-dual, or triple-dual meet by running dual-meet
    scoring independently for every unique pair of teams.
    """
    matchups: dict[tuple[str, str], dict[str, float]] = {}

    for team_a, team_b in combinations(team_ids, 2):
        pair_totals = {team_a: 0.0, team_b: 0.0}
        pair_filter = {team_a, team_b}

        for event in events:
            event_scores = score_event(
                event=event,
                entries=entries,
                results=results,
                meet_format=MeetFormat.DUAL,
                team_filter=pair_filter,
            )
            pair_totals[team_a] += event_scores.get(team_a, 0.0)
            pair_totals[team_b] += event_scores.get(team_b, 0.0)

        matchups[(team_a, team_b)] = pair_totals

    return matchups
