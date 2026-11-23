from typing import Optional


def parse_time_to_cs(time_str: str) -> int:
    """Converts 'MM:SS.cc' or 'SS.cc' into integer hundredths of a second[cite: 9]."""
    time_str = time_str.strip()
    if ":" in time_str:
        mins, secs = time_str.split(":")
        return int(mins) * 6000 + round(float(secs) * 100)
    return round(float(time_str) * 100)


def format_cs_to_time(cs: int) -> str:
    """Converts integer hundredths back to 'MM:SS.cc' or 'SS.cc'[cite: 9]."""
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
