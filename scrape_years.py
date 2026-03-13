#!/usr/bin/env python3
"""Scrape multiple seasons from AFL Tables, saving per-year files.

Usage:
    python scrape_years.py                # scrape 2016-2025 (all needed years)
    python scrape_years.py --start 2023   # scrape 2023-2025 only
"""

import argparse
import json
from pathlib import Path

from scraper.afltables import scrape_umpire_history
from scraper.analysis import build_umpire_profiles, save_profiles, DATA_DIR


def scrape_year(year: int) -> list[dict]:
    """Scrape a single year, using cache if available."""
    cache_path = DATA_DIR / f"matches_{year}.json"
    if cache_path.exists():
        matches = json.loads(cache_path.read_text())
        print(f"  {year}: loaded {len(matches)} cached matches")
        return matches

    print(f"  {year}: scraping from AFL Tables...")
    matches = scrape_umpire_history(year)
    cache_path.write_text(json.dumps(matches, indent=2))
    print(f"  {year}: saved {len(matches)} matches")
    return matches


def combine_and_build(all_matches: dict[int, list[dict]]):
    """Build 3, 5, and 10-year datasets and profiles."""
    ranges = {
        "3yr": list(range(2023, 2026)),
        "5yr": list(range(2021, 2026)),
        "10yr": list(range(2016, 2026)),
    }

    for label, years in ranges.items():
        combined = []
        missing = []
        for y in years:
            if y in all_matches:
                combined.extend(all_matches[y])
            else:
                missing.append(y)

        if missing:
            print(f"\n  {label}: missing data for {missing}, skipping")
            continue

        # Save combined match data
        out_matches = DATA_DIR / f"matches_{label}.json"
        out_matches.write_text(json.dumps(combined, indent=2))

        # Build and save profiles
        profiles = build_umpire_profiles(combined)
        out_profiles = DATA_DIR / f"umpire_profiles_{label}.json"
        save_profiles(profiles, out_profiles)

        print(f"  {label} ({years[0]}-{years[-1]}): "
              f"{len(combined)} matches, {len(profiles)} umpires")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2016,
                        help="First year to scrape (default: 2016)")
    parser.add_argument("--end", type=int, default=2025,
                        help="Last year to scrape (default: 2025)")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    all_matches = {}
    for year in range(args.start, args.end + 1):
        all_matches[year] = scrape_year(year)

    print("\nBuilding datasets...")
    combine_and_build(all_matches)
    print("\nDone!")


if __name__ == "__main__":
    main()
