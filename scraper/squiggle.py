"""Fetch current-round fixtures from the Squiggle API."""

from datetime import datetime

import requests

API_BASE = "https://api.squiggle.com.au"
USER_AGENT = "AFL-Umpire-App/0.1 (github.com/example/afl-umpire-app)"


def _get(params: dict) -> dict:
    """Make a request to the Squiggle API with a polite User-Agent."""
    resp = requests.get(
        API_BASE,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def current_season_year() -> int:
    """AFL seasons start in March, so use the current calendar year."""
    return datetime.now().year


def get_current_round_games(year: int | None = None) -> list[dict]:
    """Return the list of games for the current (or next upcoming) round.

    Squiggle returns games with a `complete` percentage — we find the earliest
    round that still has incomplete games, treating that as "current".
    """
    if year is None:
        year = current_season_year()
    data = _get({"q": "games", "year": year, "complete": 0})
    games = data.get("games", [])
    if not games:
        return []

    # Find the lowest round number among incomplete games
    min_round = min(g["round"] for g in games)
    return [g for g in games if g["round"] == min_round]


def get_round_games(year: int, round_num: int) -> list[dict]:
    """Return all games for a specific round."""
    data = _get({"q": "games", "year": year, "round": round_num})
    return data.get("games", [])


def format_fixture(game: dict) -> dict:
    """Extract the fields we care about from a Squiggle game record."""
    return {
        "game_id": game.get("id"),
        "round": game.get("round"),
        "home_team": game.get("hteam"),
        "away_team": game.get("ateam"),
        "venue": game.get("venue"),
        "date": game.get("date"),
        "localtime": game.get("localtime"),
        "is_final": game.get("is_final", False),
    }


if __name__ == "__main__":
    import json

    print("Fetching current round fixtures...")
    games = get_current_round_games()
    fixtures = [format_fixture(g) for g in games]

    print(f"Found {len(fixtures)} games in Round {fixtures[0]['round'] if fixtures else '?'}:\n")
    for f in fixtures:
        print(f"  {f['away_team']:20s} @ {f['home_team']:20s}  —  {f['venue']}")
        print(f"    {f['date']} {f['localtime'] or ''}")
        print()

    # Save for downstream use
    with open("data/current_fixtures.json", "w") as fh:
        json.dump(fixtures, fh, indent=2)
    print("Saved to data/current_fixtures.json")
