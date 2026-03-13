"""Scrape umpire and free-kick data from AFL Tables match pages."""

import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://afltables.com/afl"
USER_AGENT = "AFL-Umpire-App/0.1 (github.com/example/afl-umpire-app)"
REQUEST_DELAY = 2  # seconds between requests — be polite to AFL Tables


def _fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def get_season_games(year: int) -> list[dict]:
    """Parse the season page and return a list of game metadata with URLs.

    Each entry has: round, home_team, away_team, match_stats_url
    """
    url = f"{BASE_URL}/seas/{year}.html"
    soup = _fetch_page(url)

    games = []
    # Match-stats links follow pattern: stats/games/YYYY/XXXXXXXXXXX.html
    for link in soup.find_all("a", href=re.compile(r"stats/games/\d{4}/\d+\.html")):
        href = link["href"]
        # Resolve relative URL
        if href.startswith(".."):
            full_url = f"{BASE_URL}/{href.lstrip('../')}"
        elif href.startswith("http"):
            full_url = href
        else:
            full_url = f"{BASE_URL}/{href}"
        games.append({"url": full_url, "link_text": link.get_text(strip=True)})

    return games


def _extract_team_frees(table) -> tuple[str, int, int]:
    """Extract team name, frees-for (FF) and frees-against (FA) from a stats table.

    Stats tables have headers in row 1 (columns: #, Player, KI, MK, ... FF, FA, ...),
    a "Totals" row second-to-last, and an "Opposition" row last.
    Returns (team_name, frees_for, frees_against).
    """
    rows = table.find_all("tr")
    if len(rows) < 3:
        return ("", 0, 0)

    # Row 0 is the table title like "Sydney Match Statistics [Season...]"
    title_text = rows[0].get_text(strip=True)
    team_name = re.match(r"^(.+?)\s*Match Statistics", title_text)
    team_name = team_name.group(1) if team_name else ""

    # Row 1 has column headers
    headers = [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
    try:
        ff_idx = headers.index("FF")
        fa_idx = headers.index("FA")
    except ValueError:
        return (team_name, 0, 0)

    # "Totals" row — second-to-last
    totals_cells = [c.get_text(strip=True) for c in rows[-2].find_all(["td", "th"])]
    if not totals_cells or totals_cells[0] != "Totals":
        return (team_name, 0, 0)

    # The totals row omits the "#" column, so indices shift by 1
    try:
        frees_for = int(totals_cells[ff_idx - 1])
        frees_against = int(totals_cells[fa_idx - 1])
    except (ValueError, IndexError):
        return (team_name, 0, 0)

    return (team_name, frees_for, frees_against)


def parse_match_page(url: str) -> dict | None:
    """Scrape a single match page for umpires and free kick counts.

    Returns a dict with:
        home_team, away_team, umpires (list of names),
        home_frees_for, home_frees_against,
        away_frees_for, away_frees_against
    """
    soup = _fetch_page(url)

    tables = soup.find_all("table")
    if len(tables) < 5:
        return None

    # --- Table 0: match header with scores and umpires ---
    header_table = tables[0]
    header_rows = header_table.find_all("tr")

    # Rows 1 and 2 have team names (first cell of each row)
    team_cells = [row.find("td") or row.find("th") for row in header_rows[1:3]]
    teams = [c.get_text(strip=True).split("\xa0")[0] for c in team_cells if c]
    if len(teams) < 2:
        return None
    # Clean team names — they are followed by score digits
    home_team = re.match(r"^([A-Za-z\s.]+)", teams[0])
    away_team = re.match(r"^([A-Za-z\s.]+)", teams[1])
    home_team = home_team.group(1).strip() if home_team else teams[0]
    away_team = away_team.group(1).strip() if away_team else teams[1]

    # Umpires are in the last row of the header table
    umpire_text = header_rows[-1].get_text(" ", strip=True)
    umpires = []
    umpire_match = re.search(r"[Ff]ield\s+[Uu]mpires?\s+(.+)", umpire_text)
    if umpire_match:
        raw = umpire_match.group(1)
        umpires = [re.sub(r"\s*\(\d+\)", "", name).strip()
                   for name in raw.split(",") if name.strip()]

    # --- Tables 2 and 4: team match statistics ---
    # Table 2 = first team stats, Table 4 = second team stats
    team1_name, team1_ff, team1_fa = _extract_team_frees(tables[2])
    team2_name, team2_ff, team2_fa = _extract_team_frees(tables[4])

    # Match extracted team names to home/away
    if team1_name == home_team:
        home_ff, home_fa = team1_ff, team1_fa
        away_ff, away_fa = team2_ff, team2_fa
    else:
        home_ff, home_fa = team2_ff, team2_fa
        away_ff, away_fa = team1_ff, team1_fa

    return {
        "url": url,
        "home_team": home_team,
        "away_team": away_team,
        "umpires": umpires,
        "home_frees_for": home_ff,
        "home_frees_against": home_fa,
        "away_frees_for": away_ff,
        "away_frees_against": away_fa,
    }


def scrape_umpire_history(year: int, max_games: int | None = None) -> list[dict]:
    """Scrape all completed match pages for a season.

    Returns a list of parsed match dicts. Respects a delay between requests.
    """
    game_links = get_season_games(year)
    results = []

    for i, game in enumerate(game_links):
        if max_games and i >= max_games:
            break
        print(f"  [{i+1}/{len(game_links)}] {game['url']}")
        parsed = parse_match_page(game["url"])
        if parsed and parsed["umpires"]:
            results.append(parsed)
        time.sleep(REQUEST_DELAY)

    return results


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Scrape AFL Tables match data")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--max-games", type=int, default=None,
                        help="Limit number of games to scrape (default: all)")
    args = parser.parse_args()

    print(f"Scraping {args.year} season (max {args.max_games or 'all'} games)...\n")
    matches = scrape_umpire_history(args.year, max_games=args.max_games)

    for m in matches:
        print(f"  {m['home_team']} vs {m['away_team']}")
        print(f"    Umpires: {', '.join(m['umpires'])}")
        print(f"    Frees: {m['home_team']} {m['home_frees_for']}-{m['home_frees_against']}, "
              f"{m['away_team']} {m['away_frees_for']}-{m['away_frees_against']}")
        print()

    with open("data/match_umpire_data.json", "w") as fh:
        json.dump(matches, fh, indent=2)
    print(f"Saved {len(matches)} matches to data/match_umpire_data.json")
