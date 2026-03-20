"""Aggregate umpire free-kick data and produce per-umpire / per-team summaries.

METHODOLOGY
-----------
AFL Tables provides aggregate free kick totals per game, not per-umpire.
Each game has a crew of field umpires (typically 4) who share officiating
duties. To estimate individual umpire tendencies we:

1. Divide each game's free kick counts by the crew size to produce
   a per-umpire-per-game estimate (crew-averaged).
2. Accumulate these estimates across all games an umpire has officiated to
   build career/season averages.
3. Because umpires rotate through many different crew combinations over a
   season, the averaging naturally controls for crew effects given a
   sufficient sample size.
4. Profiles based on fewer than MIN_RELIABLE_GAMES are flagged as low-
   confidence so the UI can communicate this to users.

LIMITATION: Free kick totals include Out of Bounds on the Full (OOBOTF),
which is an automatic non-discretionary call. No public data source
separates OOBOTF from other free kicks. Since OOBOTF inflates both FF
and FA roughly equally, the *differential* (FF - FA) remains a valid
signal of umpire tendency — but absolute FF/FA values are higher than
they would be for discretionary calls alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

MIN_RELIABLE_GAMES = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UmpireTeamRecord:
    """Crew-averaged free kick record for one umpire + one team."""
    team: str
    games: int = 0
    # These store crew-averaged (divided by crew_size) cumulative values
    total_frees_for: float = 0.0
    total_frees_against: float = 0.0
    # Home/away splits
    home_games: int = 0
    home_frees_for: float = 0.0
    home_frees_against: float = 0.0
    away_games: int = 0
    away_frees_for: float = 0.0
    away_frees_against: float = 0.0

    @property
    def avg_frees_for(self) -> float:
        return self.total_frees_for / self.games if self.games else 0.0

    @property
    def avg_frees_against(self) -> float:
        return self.total_frees_against / self.games if self.games else 0.0

    @property
    def avg_differential(self) -> float:
        """Positive = team gets more frees than opponents on average."""
        return self.avg_frees_for - self.avg_frees_against

    # Home split averages
    @property
    def avg_home_differential(self) -> float | None:
        if not self.home_games:
            return None
        return (self.home_frees_for / self.home_games) - (self.home_frees_against / self.home_games)

    # Away split averages
    @property
    def avg_away_differential(self) -> float | None:
        if not self.away_games:
            return None
        return (self.away_frees_for / self.away_games) - (self.away_frees_against / self.away_games)

    @property
    def is_reliable(self) -> bool:
        return self.games >= MIN_RELIABLE_GAMES

    def to_dict(self) -> dict:
        d = {
            "team": self.team,
            "games": self.games,
            "total_frees_for": round(self.total_frees_for, 2),
            "total_frees_against": round(self.total_frees_against, 2),
            "avg_frees_for": round(self.avg_frees_for, 1),
            "avg_frees_against": round(self.avg_frees_against, 1),
            "avg_differential": round(self.avg_differential, 1),
            "is_reliable": self.is_reliable,
            "home_games": self.home_games,
            "home_frees_for": round(self.home_frees_for, 2),
            "home_frees_against": round(self.home_frees_against, 2),
            "away_games": self.away_games,
            "away_frees_for": round(self.away_frees_for, 2),
            "away_frees_against": round(self.away_frees_against, 2),
        }
        if self.home_games:
            d["avg_home_ff"] = round(self.home_frees_for / self.home_games, 1)
            d["avg_home_fa"] = round(self.home_frees_against / self.home_games, 1)
            d["avg_home_differential"] = round(self.avg_home_differential, 1)
        if self.away_games:
            d["avg_away_ff"] = round(self.away_frees_for / self.away_games, 1)
            d["avg_away_fa"] = round(self.away_frees_against / self.away_games, 1)
            d["avg_away_differential"] = round(self.avg_away_differential, 1)
        return d


@dataclass
class UmpireProfile:
    """Aggregated crew-averaged stats for a single umpire."""
    name: str
    total_games: int = 0
    team_records: dict[str, UmpireTeamRecord] = field(default_factory=dict)

    @property
    def avg_total_frees_per_game(self) -> float:
        """Average crew-averaged free kicks per game (both teams combined)."""
        total = sum(r.total_frees_for for r in self.team_records.values())
        return total / self.total_games if self.total_games else 0.0

    @property
    def is_reliable(self) -> bool:
        return self.total_games >= MIN_RELIABLE_GAMES

    def record_for(self, team: str) -> UmpireTeamRecord:
        if team not in self.team_records:
            self.team_records[team] = UmpireTeamRecord(team=team)
        return self.team_records[team]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total_games": self.total_games,
            "avg_total_frees_per_game": round(self.avg_total_frees_per_game, 1),
            "is_reliable": self.is_reliable,
            "team_records": {
                team: rec.to_dict() for team, rec in sorted(self.team_records.items())
            },
        }


# ---------------------------------------------------------------------------
# Build profiles from scraped match data
# ---------------------------------------------------------------------------

def build_umpire_profiles(matches: list[dict]) -> dict[str, UmpireProfile]:
    """Build an UmpireProfile for every umpire found in the match data.

    Free kick counts are divided by crew size (number of field umpires in that
    game) to produce crew-averaged per-umpire estimates.

    Args:
        matches: list of dicts as produced by afltables.parse_match_page()

    Returns:
        dict mapping umpire name -> UmpireProfile
    """
    profiles: dict[str, UmpireProfile] = {}

    for match in matches:
        home = match["home_team"]
        away = match["away_team"]
        umpires = match["umpires"]
        crew_size = len(umpires)
        if crew_size == 0:
            continue

        # Crew-averaged free kick shares
        h_ff = match["home_frees_for"] / crew_size
        h_fa = match["home_frees_against"] / crew_size
        a_ff = match["away_frees_for"] / crew_size
        a_fa = match["away_frees_against"] / crew_size

        for umpire_name in umpires:
            if umpire_name not in profiles:
                profiles[umpire_name] = UmpireProfile(name=umpire_name)
            profile = profiles[umpire_name]
            profile.total_games += 1

            home_rec = profile.record_for(home)
            home_rec.games += 1
            home_rec.total_frees_for += h_ff
            home_rec.total_frees_against += h_fa
            home_rec.home_games += 1
            home_rec.home_frees_for += h_ff
            home_rec.home_frees_against += h_fa

            away_rec = profile.record_for(away)
            away_rec.games += 1
            away_rec.total_frees_for += a_ff
            away_rec.total_frees_against += a_fa
            away_rec.away_games += 1
            away_rec.away_frees_for += a_ff
            away_rec.away_frees_against += a_fa

    return profiles


# ---------------------------------------------------------------------------
# Fixture analysis — the main user-facing query
# ---------------------------------------------------------------------------

@dataclass
class FixtureUmpireReport:
    """Report for a single umpire in a specific upcoming fixture."""
    umpire: str
    total_games: int
    is_reliable: bool
    home_team: str
    away_team: str
    home_record: dict | None
    away_record: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def analyse_fixture(
    home_team: str,
    away_team: str,
    umpire_names: list[str],
    profiles: dict[str, UmpireProfile],
) -> list[FixtureUmpireReport]:
    """For a given fixture and its assigned umpires, produce a report.

    Shows each umpire's crew-averaged free-kick record when officiating
    games involving the home team and the away team.
    """
    reports = []
    for name in umpire_names:
        profile = profiles.get(name)
        if profile is None:
            reports.append(FixtureUmpireReport(
                umpire=name,
                total_games=0,
                is_reliable=False,
                home_team=home_team,
                away_team=away_team,
                home_record=None,
                away_record=None,
            ))
            continue

        home_rec = profile.team_records.get(home_team)
        away_rec = profile.team_records.get(away_team)

        reports.append(FixtureUmpireReport(
            umpire=name,
            total_games=profile.total_games,
            is_reliable=profile.is_reliable,
            home_team=home_team,
            away_team=away_team,
            home_record=home_rec.to_dict() if home_rec else None,
            away_record=away_rec.to_dict() if away_rec else None,
        ))

    return reports


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def save_profiles(profiles: dict[str, UmpireProfile], path: Path | None = None):
    path = path or DATA_DIR / "umpire_profiles.json"
    data = {name: p.to_dict() for name, p in sorted(profiles.items())}
    path.write_text(json.dumps(data, indent=2))
    print(f"Saved {len(data)} umpire profiles to {path}")


def load_profiles(path: Path | None = None) -> dict[str, UmpireProfile]:
    """Load profiles from JSON back into UmpireProfile objects."""
    path = path or DATA_DIR / "umpire_profiles.json"
    raw = json.loads(path.read_text())
    profiles = {}
    for name, data in raw.items():
        profile = UmpireProfile(name=name, total_games=data["total_games"])
        for team, rec_data in data.get("team_records", {}).items():
            rec = UmpireTeamRecord(
                team=team,
                games=rec_data["games"],
                total_frees_for=rec_data["total_frees_for"],
                total_frees_against=rec_data["total_frees_against"],
                home_games=rec_data.get("home_games", 0),
                home_frees_for=rec_data.get("home_frees_for", 0.0),
                home_frees_against=rec_data.get("home_frees_against", 0.0),
                away_games=rec_data.get("away_games", 0),
                away_frees_for=rec_data.get("away_frees_for", 0.0),
                away_frees_against=rec_data.get("away_frees_against", 0.0),
            )
            profile.team_records[team] = rec
        profiles[name] = profile
    return profiles


def load_matches(path: Path | None = None) -> list[dict]:
    path = path or DATA_DIR / "match_umpire_data.json"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_RELIABILITY_NOTE = " *" # appended to low-sample entries


def _print_fixture_report(reports: list[FixtureUmpireReport]):
    for r in reports:
        reliability = "" if r.is_reliable else "  [low sample]"
        print(f"\n  {r.umpire}  ({r.total_games} games){reliability}")
        for label, rec in [("Home", r.home_record), ("Away", r.away_record)]:
            team = r.home_team if label == "Home" else r.away_team
            if rec is None:
                print(f"    {team:25s}  -- no history")
            else:
                flag = "" if rec["is_reliable"] else " *"
                print(f"    {team:25s}  {rec['games']:3d} games  "
                      f"avg FF {rec['avg_frees_for']:4.1f}  "
                      f"avg FA {rec['avg_frees_against']:4.1f}  "
                      f"diff {rec['avg_differential']:+.1f}{flag}")

    has_unreliable = any(
        not r.is_reliable
        or (r.home_record and not r.home_record.get("is_reliable", True))
        or (r.away_record and not r.away_record.get("is_reliable", True))
        for r in reports
    )
    if has_unreliable:
        print(f"\n  * fewer than {MIN_RELIABLE_GAMES} games — estimate less reliable")
    print("  (Crew-averaged free kicks — includes OOBOTF; differential unaffected)")


if __name__ == "__main__":
    print("Loading match data...")
    matches = load_matches()
    print(f"  {len(matches)} matches loaded\n")

    print("Building umpire profiles (crew-averaged)...")
    profiles = build_umpire_profiles(matches)
    print(f"  {len(profiles)} umpires found\n")

    save_profiles(profiles)

    # Demo: show every umpire's record for a sample team
    sample_team = "Sydney"
    print(f"\n--- Umpire records involving {sample_team} ---")
    for name, profile in sorted(profiles.items()):
        rec = profile.team_records.get(sample_team)
        if rec and rec.games > 0:
            flag = "" if rec.is_reliable else " *"
            print(f"  {name:25s}  {rec.games:3d} games  "
                  f"avg FF {rec.avg_frees_for:4.1f}  "
                  f"avg FA {rec.avg_frees_against:4.1f}  "
                  f"diff {rec.avg_differential:+.1f}{flag}")
    print(f"\n  * fewer than {MIN_RELIABLE_GAMES} games — estimate less reliable")
    print("  (Crew-averaged free kicks — includes OOBOTF; differential unaffected)")
