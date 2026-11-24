from typing import Optional


def parse_time_to_cs(time_str: str) -> int:
    """
    Converts swim times into integer hundredths of a second (centiseconds).

    Supports:
    - Digit-only entry: '2451' -> 24.51s (2451 cs), '14520' -> 1:45.20 (10520 cs)
    - Formatted entry: '24.51' or '1:45.20'
    """
    if not time_str or not time_str.strip():
        raise ValueError("Time string cannot be empty.")

    cleaned = time_str.strip()

    # Digit-only shortcut: last 2 digits = hundredths, next 2 = seconds, rest = minutes
    if cleaned.isdigit():
        padded = cleaned.zfill(3)
        hundredths = int(padded[-2:])
        seconds = int(padded[-4:-2])
        minutes = int(padded[:-4]) if len(padded) > 4 else 0

        if seconds >= 60:
            raise ValueError(f"Seconds must be less than 60 in '{time_str}'.")

        return (minutes * 6000) + (seconds * 100) + hundredths

    if ":" in cleaned:
        parts = cleaned.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format '{time_str}'. Use MM:SS.cc or SS.cc.")
        mins_str, secs_str = parts
        try:
            mins = int(mins_str)
            secs_val = float(secs_str)
        except ValueError as exc:
            raise ValueError(f"Invalid time format '{time_str}'.") from exc

        if mins < 0 or secs_val < 0 or secs_val >= 60:
            raise ValueError(f"Invalid minutes or seconds in '{time_str}'.")

        return mins * 6000 + round(secs_val * 100)

    try:
        secs_val = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid time format '{time_str}'.") from exc

    if secs_val < 0:
        raise ValueError(f"Time cannot be negative in '{time_str}'.")

    return round(secs_val * 100)


def format_cs_to_time(cs: int) -> str:
    """Converts integer hundredths back to 'MM:SS.cc' or 'SS.cc'."""
    mins, rem = divmod(cs, 6000)
    secs, hundredths = divmod(rem, 100)
    if mins > 0:
        return f"{mins}:{secs:02d}.{hundredths:02d}"
    return f"{secs}.{hundredths:02d}"


def calculate_official_time(
    watch_time_cs: Optional[int],
    backup_times_cs: list[int],
    watch_malfunction: bool = False,
) -> Optional[int]:
    """NFHS Rule 6 timing hierarchy using primary watch time and backup times."""
    if watch_time_cs is not None and not watch_malfunction:
        return watch_time_cs

    valid_backups = sorted(t for t in backup_times_cs if t > 0)
    count = len(valid_backups)

    if count == 3:
        return valid_backups[1]  # Middle (median) time
    if count == 2:
        # Integer division (//) truncates thousandths per NFHS rules
        return (valid_backups[0] + valid_backups[1]) // 2
    if count == 1:
        return valid_backups[0]
    return None
