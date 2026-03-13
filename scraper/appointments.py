"""Fetch weekly umpire appointments from AFLUA PDFs."""

from __future__ import annotations

import re
import tempfile
import os
from dataclasses import dataclass, asdict

import requests
import fitz  # PyMuPDF

AFLUA_PDF_BASE = "https://aflua.com.au/wp-content/uploads"
USER_AGENT = "AFL-Umpire-App/0.1 (github.com/example/afl-umpire-app)"

# AFLUA uses slightly different team names than Squiggle/AFL Tables.
# This map normalises AFLUA names to match AFL Tables conventions.
TEAM_NAME_MAP = {
    "GWS Giants": "Greater Western Sydney",
    "GWS": "Greater Western Sydney",
    "Brisbane": "Brisbane Lions",
    "Kangaroos": "North Melbourne",
}


def _normalise_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


@dataclass
class MatchAppointment:
    """Umpire appointments for a single match."""
    date: str
    home_team: str
    away_team: str
    venue: str
    time: str
    field_umpires: list[str]
    boundary_umpires: list[str]
    goal_umpires: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _build_pdf_url(year: int, month: int, round_num: int) -> str:
    return f"{AFLUA_PDF_BASE}/{year}/{month:02d}/Round-{round_num}.pdf"


def _download_pdf(url: str) -> str | None:
    """Download a PDF to a temp file and return the path, or None on failure."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    if resp.status_code != 200:
        return None
    path = os.path.join(tempfile.gettempdir(), "aflua_round.pdf")
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def _extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _strip_umpire_number(name: str) -> str:
    """Remove leading badge number, e.g. '17 - John Howorth' -> 'John Howorth'."""
    return re.sub(r"^\d+\s*-\s*", "", name).strip()


def parse_appointments_text(text: str) -> list[MatchAppointment]:
    """Parse the extracted PDF text into MatchAppointment objects.

    The PDF structure repeats this pattern per game:
        DATE
        AFL MATCH
        VENUE
        TIME
        <date line>
        <home team>
        vs.
        <away team>
        <venue>
        <time>
        UMPIRES
        FIELD UMPIRES
        <name> ...
        BOUNDARY UMPIRES
        <name> ...
        GOAL UMPIRES
        <name> ...
        EM: <name>
    """
    # Split into game blocks — each starts with a DATE header followed by
    # AFL MATCH / VENUE / TIME headers, then the actual values.
    # We split on the "DATE" keyword that appears as a column header.
    blocks = re.split(r"\nDATE\s*\n", text)

    appointments = []
    for block in blocks:
        block = block.strip()
        if not block or "FIELD UMPIRES" not in block:
            continue

        lines = [l.strip() for l in block.splitlines() if l.strip()]

        # Skip the header row tokens (AFL MATCH, VENUE, TIME)
        # and find the actual date line (e.g. "Thursday, March 12, 2026")
        date_line = ""
        data_start = 0
        for i, line in enumerate(lines):
            if re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", line):
                date_line = line
                data_start = i
                break

        if not date_line:
            continue

        # After the date line, the next lines are:
        # home_team, "vs.", away_team, venue, time
        rest = lines[data_start + 1:]

        # Find "vs." to split teams
        vs_idx = None
        for i, line in enumerate(rest):
            if line.lower() == "vs.":
                vs_idx = i
                break

        if vs_idx is None or vs_idx < 1:
            continue

        home_team = _normalise_team(rest[vs_idx - 1])
        away_team = _normalise_team(rest[vs_idx + 1])

        # Venue and time follow the away team
        venue = rest[vs_idx + 2] if len(rest) > vs_idx + 2 else ""
        time_str = rest[vs_idx + 3] if len(rest) > vs_idx + 3 else ""

        # Parse umpire sections
        field_umpires = []
        boundary_umpires = []
        goal_umpires = []

        current_section = None
        for line in rest:
            if line == "FIELD UMPIRES":
                current_section = "field"
                continue
            elif line == "BOUNDARY UMPIRES":
                current_section = "boundary"
                continue
            elif line == "GOAL UMPIRES":
                current_section = "goal"
                continue
            elif line in ("UMPIRES", "AFL MATCH", "VENUE", "TIME"):
                continue

            if current_section == "field":
                if line.startswith("EM:") or line == "BOUNDARY UMPIRES":
                    continue
                field_umpires.append(_strip_umpire_number(line))
            elif current_section == "boundary":
                if line.startswith("EM:") or line == "GOAL UMPIRES":
                    continue
                boundary_umpires.append(line)
            elif current_section == "goal":
                if line.startswith("EM:"):
                    continue
                goal_umpires.append(line)

        appointments.append(MatchAppointment(
            date=date_line,
            home_team=home_team,
            away_team=away_team,
            venue=venue,
            time=time_str,
            field_umpires=field_umpires,
            boundary_umpires=boundary_umpires,
            goal_umpires=goal_umpires,
        ))

    return appointments


def fetch_round_appointments(
    year: int,
    round_num: int,
    month: int | None = None,
) -> list[MatchAppointment]:
    """Fetch umpire appointments for a given round.

    The AFLUA uploads PDFs at a predictable URL pattern. The month in the URL
    corresponds to when the PDF was uploaded (roughly when the round is played).
    If month is not provided, we try likely months for the AFL season (March-September).
    """
    if month is not None:
        months_to_try = [month]
    else:
        # AFL season runs March-September; try the most likely months
        months_to_try = list(range(3, 10))

    for m in months_to_try:
        url = _build_pdf_url(year, m, round_num)
        pdf_path = _download_pdf(url)
        if pdf_path is not None:
            print(f"  Found PDF: {url}")
            text = _extract_text(pdf_path)
            return parse_appointments_text(text)

    print(f"  No PDF found for {year} Round {round_num}")
    return []


if __name__ == "__main__":
    import json

    print("Fetching Round 1 2026 umpire appointments...\n")
    appointments = fetch_round_appointments(2026, 1)

    for a in appointments:
        print(f"  {a.home_team} vs {a.away_team}")
        print(f"    {a.date} — {a.venue}, {a.time}")
        print(f"    Field: {', '.join(a.field_umpires)}")
        print()

    out = [a.to_dict() for a in appointments]
    with open("data/appointments.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {len(out)} appointments to data/appointments.json")
