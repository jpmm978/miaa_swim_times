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
