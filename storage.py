def parse_roster_csv(file_bytes: bytes) -> list[tuple[str, str]]:
    """Flexibly parses a roster CSV (with or without headers) into [(name, 'F'|'M'), ...]."""
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    rows = list(csv.reader(io.StringIO(text)))
    swimmers: list[tuple[str, str]] = []

    for idx, row in enumerate(rows):
        cells = [c.strip() for c in row if c.strip()]
        if len(cells) < 2:
            continue

        # Skip header row if present
        if idx == 0 and cells[0].lower() in ("name", "swimmer", "athlete", "last", "last name"):
            continue

        # Last cell is gender; everything before it is the swimmer's name
        raw_gender = cells[-1].upper()
        name = " ".join(cells[:-1]).strip()

        if raw_gender.startswith(("F", "G")):
            gender = "F"
        elif raw_gender.startswith(("M", "B")):
            gender = "M"
        else:
            continue

        if name:
            swimmers.append((name, gender))

    return swimmers
