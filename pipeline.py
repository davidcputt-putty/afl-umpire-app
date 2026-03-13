#!/usr/bin/env python3
"""End-to-end pipeline: scrape fixtures, build profiles, produce reports.

Usage:
    # Full scrape + analysis for a season (slow — scrapes AFL Tables)
    python pipeline.py --scrape --year 2025

    # Fetch this week's umpire appointments and analyse (default: 3yr dataset)
    python pipeline.py --round 1

    # Use a larger dataset for deeper history
    python pipeline.py --round 1 --dataset 10yr

    # Analyse a specific fixture with known umpires
    python pipeline.py --home "Sydney" --away "Hawthorn" \
        --umpires "Brendan Hosking,Simon Meredith,Jacob Mollison"
"""

import argparse
import json
from pathlib import Path

from scraper.squiggle import get_current_round_games, format_fixture, current_season_year
from scraper.afltables import scrape_umpire_history
from scraper.appointments import fetch_round_appointments
from scraper.analysis import (
    build_umpire_profiles,
    analyse_fixture,
    save_profiles,
    load_profiles,
    load_matches,
    _print_fixture_report,
    DATA_DIR,
)


def cmd_scrape(year: int, max_games: int | None):
    """Scrape a full season from AFL Tables and save match data."""
    print(f"Scraping {year} season from AFL Tables...\n")
    matches = scrape_umpire_history(year, max_games=max_games)

    out = DATA_DIR / "match_umpire_data.json"
    out.write_text(json.dumps(matches, indent=2))
    print(f"\nSaved {len(matches)} matches to {out}")
    return matches


VALID_DATASETS = ("3yr", "5yr", "10yr")


def _resolve_profile_path(dataset: str) -> Path:
    """Return the profile JSON path for a dataset label, falling back if needed."""
    if dataset in VALID_DATASETS:
        path = DATA_DIR / f"umpire_profiles_{dataset}.json"
        if path.exists():
            return path
        # Fall back to default profiles with a warning
        fallback = DATA_DIR / "umpire_profiles.json"
        if fallback.exists():
            print(f"  Note: {dataset} profiles not found, using default profiles.")
            print(f"  Run 'python scrape_years.py' to build {dataset} dataset.\n")
            return fallback
        return path  # will raise FileNotFoundError downstream
    return DATA_DIR / "umpire_profiles.json"


def cmd_build_profiles(matches: list[dict] | None = None, dataset: str | None = None):
    """Build umpire profiles from scraped data."""
    if matches is None:
        matches = load_matches()
    print(f"Building profiles from {len(matches)} matches...")
    profiles = build_umpire_profiles(matches)
    save_profiles(profiles, _resolve_profile_path(dataset) if dataset else None)
    return profiles


def cmd_fixtures():
    """Fetch and display current round fixtures from Squiggle."""
    print("Fetching current round from Squiggle...\n")
    games = get_current_round_games()
    fixtures = [format_fixture(g) for g in games]

    if not fixtures:
        print("No upcoming games found.")
        return fixtures

    rnd = fixtures[0]["round"]
    print(f"Round {rnd}:")
    for f in fixtures:
        print(f"  {f['away_team']:25s} @ {f['home_team']:25s}  -- {f['venue']}")
        print(f"    {f['date']}")
    print()

    out = DATA_DIR / "current_fixtures.json"
    out.write_text(json.dumps(fixtures, indent=2))
    return fixtures


def cmd_appointments(year: int, round_num: int):
    """Fetch umpire appointments for a round from AFLUA."""
    print(f"Fetching umpire appointments for {year} Round {round_num}...\n")
    appointments = fetch_round_appointments(year, round_num)

    if not appointments:
        print("  No appointments found (PDF may not be published yet).")
        return []

    for a in appointments:
        print(f"  {a.home_team} vs {a.away_team}")
        print(f"    {a.date} -- {a.venue}, {a.time}")
        print(f"    Field: {', '.join(a.field_umpires)}")
    print()

    out = DATA_DIR / "appointments.json"
    data = [a.to_dict() for a in appointments]
    Path(out).write_text(json.dumps(data, indent=2))
    return appointments


def cmd_analyse_fixture(home: str, away: str, umpire_names: list[str], dataset: str = "3yr"):
    """Analyse a specific fixture given umpire names."""
    profiles = load_profiles(_resolve_profile_path(dataset))
    reports = analyse_fixture(home, away, umpire_names, profiles)

    print(f"\n{'='*60}")
    print(f"  {away} @ {home}")
    print(f"  Umpires: {', '.join(umpire_names)}")
    print(f"{'='*60}")
    _print_fixture_report(reports)
    print()

    return [r.to_dict() for r in reports]


def cmd_analyse_round(year: int, round_num: int, dataset: str = "3yr"):
    """Fetch appointments, load profiles, and analyse every fixture in a round."""
    appointments = cmd_appointments(year, round_num)
    if not appointments:
        return

    profile_path = _resolve_profile_path(dataset)
    profiles = load_profiles(profile_path)
    print(f"Analysing {len(appointments)} fixtures against "
          f"{len(profiles)} umpire profiles ({dataset} dataset)...\n")

    all_reports = []
    for a in appointments:
        reports = analyse_fixture(a.home_team, a.away_team, a.field_umpires, profiles)

        print(f"{'='*60}")
        print(f"  {a.away_team} @ {a.home_team}  -- {a.venue}")
        print(f"  {a.date}, {a.time}")
        print(f"  Field umpires: {', '.join(a.field_umpires)}")
        print(f"{'='*60}")
        _print_fixture_report(reports)
        print()

        all_reports.append({
            "home_team": a.home_team,
            "away_team": a.away_team,
            "venue": a.venue,
            "date": a.date,
            "time": a.time,
            "umpire_reports": [r.to_dict() for r in reports],
        })

    out = DATA_DIR / "round_analysis.json"
    Path(out).write_text(json.dumps(all_reports, indent=2))
    print(f"Saved analysis to {out}")
    return all_reports


def main():
    parser = argparse.ArgumentParser(description="AFL Umpire Free Kick Pipeline")
    parser.add_argument("--scrape", action="store_true",
                        help="Scrape match data from AFL Tables")
    parser.add_argument("--year", type=int, default=None,
                        help="Season year (default: current year)")
    parser.add_argument("--max-games", type=int, default=None,
                        help="Max games to scrape (default: all)")
    parser.add_argument("--round", type=int, default=None,
                        help="Round number to fetch appointments and analyse")
    parser.add_argument("--home", type=str, help="Home team for fixture analysis")
    parser.add_argument("--away", type=str, help="Away team for fixture analysis")
    parser.add_argument("--umpires", type=str,
                        help="Comma-separated umpire names for fixture analysis")
    parser.add_argument("--dataset", type=str, default="3yr",
                        choices=VALID_DATASETS,
                        help="Historical dataset to use: 3yr, 5yr, 10yr (default: 3yr)")
    args = parser.parse_args()

    year = args.year or current_season_year()
    DATA_DIR.mkdir(exist_ok=True)

    if args.scrape:
        matches = cmd_scrape(args.year or 2025, args.max_games)
        cmd_build_profiles(matches)
    elif args.round is not None:
        profile_path = _resolve_profile_path(args.dataset)
        if not profile_path.exists():
            print(f"No {args.dataset} profiles found at {profile_path}")
            print("Run scrape_years.py first to build datasets:")
            print("  python scrape_years.py")
            return
        cmd_analyse_round(year, args.round, args.dataset)
    elif args.home and args.away and args.umpires:
        umpire_names = [u.strip() for u in args.umpires.split(",")]
        cmd_analyse_fixture(args.home, args.away, umpire_names, args.dataset)
    else:
        cmd_fixtures()


if __name__ == "__main__":
    main()
