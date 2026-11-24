from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EventType(Enum):
    INDIVIDUAL = "INDIVIDUAL"
    RELAY = "RELAY"
    DIVING = "DIVING"


class ResultStatus(Enum):
    OK = "OK"
    DQ = "DQ"
    NS = "NS"   # No Show
    DFS = "DFS" # Declared False Start
    DNF = "DNF" # Did Not Finish


@dataclass
class Athlete:
    athlete_id: str
    team_id: str
    name: str
    gender: str  # "F" or "M"


@dataclass
class Event:
    event_number: int
    name: str
    event_type: EventType
    gender: str


@dataclass
class Entry:
    entry_id: str
    event_number: int
    team_id: str
    athlete_ids: list[str]  # 1 ID for individual/diving, up to 4 IDs for relays
    is_exhibition: bool = False
    relay_letter: Optional[str] = None  # "A", "B", "C"
    heat_number: int = 1        # Heat 1 scores; Heat 2+ are exhibition heats


@dataclass
class Result:
    entry_id: str
    watch_time_cs: Optional[int] = None
    backup_times_cs: list[int] = field(default_factory=list)
    diving_score: Optional[float] = None
    status: ResultStatus = ResultStatus.OK
    official_time_cs: Optional[int] = None
    manual_place: Optional[int] = None  # Official Judge's Decision (JD) override
    override_note: str = ""             # Optional note for the override
    place: Optional[int] = None
    points: float = 0.0


# --- 2026-2027 MIAA Winter Qualifying Standards (GAR: C.West & Div I) ---

GAR_TEAM_ID = "GAR"
GAR_SECTION = "C.West"
GAR_STATE_DIVISION = "Div I"

# Swimming cuts stored in centiseconds (int) to match Result.official_time_cs
# 1M Diving cuts stored as minimum 6-dive score (float, must achieve x2)
MIAA_WINTER_2026_27_CUTS: dict[str, dict[str, dict[str, int | float]]] = {
    "M": {
        "200 Medley Relay": {"C.West": 11959, "Div I": 10747},
        "200 Freestyle":    {"C.West": 12599, "Div I": 11461},
        "200 IM":           {"C.West": 14218, "Div I": 12894},
        "50 Freestyle":     {"C.West": 2523,  "Div I": 2326},
        "1M Diving":        {"C.West": 150.0, "Div I": 193.0},
        "100 Butterfly":    {"C.West": 6401,  "Div I": 5701},
        "100 Freestyle":    {"C.West": 5553,  "Div I": 5134},
        "500 Freestyle":    {"C.West": 34982, "Div I": 31516},
        "200 Free Relay":   {"C.West": 10593, "Div I": 9650},
        "100 Backstroke":   {"C.West": 6668,  "Div I": 5861},
        "100 Breaststroke": {"C.West": 7158,  "Div I": 6467},
        "400 Free Relay":   {"C.West": 24635, "Div I": 21466},
    },
    "F": {
        "200 Medley Relay": {"C.West": 13264, "Div I": 12626},
        "200 Freestyle":    {"C.West": 13688, "Div I": 13019},
        "200 IM":           {"C.West": 15584, "Div I": 14829},
        "50 Freestyle":     {"C.West": 2761,  "Div I": 2688},
        "1M Diving":        {"C.West": 150.0, "Div I": 185.0},
        "100 Butterfly":    {"C.West": 6993,  "Div I": 6691},
        "100 Freestyle":    {"C.West": 6176,  "Div I": 5939},
        "500 Freestyle":    {"C.West": 36884, "Div I": 34754},
        "200 Free Relay":   {"C.West": 11672, "Div I": 11183},
        "100 Backstroke":   {"C.West": 7126,  "Div I": 6728},
        "100 Breaststroke": {"C.West": 7999,  "Div I": 7762},
        "400 Free Relay":   {"C.West": 26080, "Div I": 24660},
    },
}

# Maps common event name variations (e.g. "200 Free", "Boys 50 Free") to canonical cut keys
_EVENT_ALIASES: dict[str, str] = {
    "200 medley relay": "200 Medley Relay",
    "200 free": "200 Freestyle",
    "200 freestyle": "200 Freestyle",
    "200 im": "200 IM",
    "50 free": "50 Freestyle",
    "50 freestyle": "50 Freestyle",
    "1m diving": "1M Diving",
    "1 m diving": "1M Diving",
    "diving": "1M Diving",
    "100 fly": "100 Butterfly",
    "100 butterfly": "100 Butterfly",
    "100 free": "100 Freestyle",
    "100 freestyle": "100 Freestyle",
    "500 free": "500 Freestyle",
    "500 freestyle": "500 Freestyle",
    "200 free relay": "200 Free Relay",
    "200 freestyle relay": "200 Free Relay",
    "100 back": "100 Backstroke",
    "100 backstroke": "100 Backstroke",
    "100 breast": "100 Breaststroke",
    "100 breaststroke": "100 Breaststroke",
    "400 free relay": "400 Free Relay",
    "400 freestyle relay": "400 Free Relay",
}


def normalize_cut_event_name(event_name: str) -> str:
    cleaned = event_name.strip().lower()
    for prefix in ("boys ", "girls ", "men ", "women ", "mens ", "womens "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return _EVENT_ALIASES.get(cleaned, event_name.strip())


def get_gar_cut_standards(gender: str, event_name: str) -> Optional[dict[str, int | float]]:
    """Return {'C.West': ..., 'Div I': ...} for GAR using 'M'/'F' gender and Event.name."""
    gender_key = gender.strip().upper()
    if gender_key in ("BOYS", "MEN"):
        gender_key = "M"
    elif gender_key in ("GIRLS", "WOMEN"):
        gender_key = "F"
    canonical_event = normalize_cut_event_name(event_name)
    return MIAA_WINTER_2026_27_CUTS.get(gender_key, {}).get(canonical_event)
