from models import Entry, Event, EventType


def validate_athlete_entries(
    athlete_id: str,
    entries: list[Entry],
    events_by_num: dict[int, Event],
) -> list[str]:
    """Returns a list of rule violation messages (empty list if valid)."""
    errors = []
    athlete_entries = [e for e in entries if athlete_id in e.athlete_ids]

    total_events = len(athlete_entries)
    individual_events = sum(
        1
        for e in athlete_entries
        if events_by_num[e.event_number].event_type in (EventType.INDIVIDUAL, EventType.DIVING)
    )

    if total_events > 4:
        errors.append(f"Athlete {athlete_id} entered in {total_events} events (max 4).")
    if individual_events > 2:
        errors.append(
            f"Athlete {athlete_id} entered in {individual_events} individual events (max 2)."
        )

    return errors
