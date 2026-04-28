"""Event matching between Polymarket markets and bookmaker events.

Uses fuzzy string matching to find corresponding events across platforms.
"""

import re
from datetime import timedelta

from loguru import logger
from rapidfuzz import fuzz

from src.config import settings
from src.models.events import BookmakerOdds, PolymarketMarket, SportEvent

TEAM_ALIASES: dict[str, list[str]] = {
    "los angeles lakers": ["lakers", "la lakers", "l.a. lakers"],
    "golden state warriors": ["warriors", "gsw", "gs warriors"],
    "boston celtics": ["celtics", "boston"],
    "miami heat": ["heat", "miami"],
    "new york knicks": ["knicks", "ny knicks", "new york"],
    "real madrid": ["real", "реал мадрид", "реал"],
    "barcelona": ["barca", "барселона", "барса"],
    "manchester united": ["man utd", "man united", "манчестер юнайтед", "ман юнайтед"],
    "manchester city": ["man city", "манчестер сити", "ман сити"],
    "liverpool": ["ливерпуль"],
    "chelsea": ["челси"],
    "arsenal": ["арсенал"],
    "bayern munich": ["bayern", "бавария", "бавария мюнхен"],
    "paris saint-germain": ["psg", "псж", "пари сен-жермен"],
    "juventus": ["juve", "ювентус"],
    "ac milan": ["milan", "милан"],
    "inter milan": ["inter", "интер"],
}


def normalize_team_name(name: str) -> str:
    """Normalize team name for comparison."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)

    for canonical, aliases in TEAM_ALIASES.items():
        if name in aliases or name == canonical:
            return canonical

    return name


def extract_teams_from_question(question: str) -> tuple[str, str] | None:
    """Extract two team names from a Polymarket question.

    Handles patterns like:
    - "Will X beat Y?"
    - "X vs Y"
    - "X to win against Y"
    - "Winner of X vs Y?"
    """
    question_lower = question.lower()

    patterns = [
        r"will (.+?) (?:beat|defeat|win against) (.+?)[\?\.]",
        r"(.+?) vs\.?\s+(.+?)[\?\.\s]",
        r"(.+?) to win (?:against|over|vs\.?) (.+?)[\?\.]",
        r"winner.*?:\s*(.+?)\s+(?:vs\.?|or)\s+(.+?)[\?\.]",
        r"(.+?)\s*[-–—]\s*(.+?)[\?\.]",
    ]

    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            team1 = normalize_team_name(match.group(1))
            team2 = normalize_team_name(match.group(2))
            if team1 and team2 and team1 != team2:
                return team1, team2

    return None


class EventMatcher:
    """Matches Polymarket markets to bookmaker events."""

    def __init__(self, threshold: int | None = None) -> None:
        self.threshold = threshold or settings.fuzzy_match_threshold

    def match_market_to_events(
        self,
        market: PolymarketMarket,
        bk_events: list[BookmakerOdds],
    ) -> BookmakerOdds | None:
        """Find the best matching bookmaker event for a Polymarket market."""
        teams = extract_teams_from_question(market.question)
        if not teams:
            return None

        poly_home, poly_away = teams
        best_match: BookmakerOdds | None = None
        best_score: float = 0

        for bk in bk_events:
            score = self._compute_match_score(
                poly_home, poly_away, bk.event, market
            )
            if score > best_score and score >= self.threshold:
                best_score = score
                best_match = bk

        if best_match:
            logger.debug(
                f"Matched: '{market.question}' -> "
                f"'{best_match.event.display_name}' ({best_match.bookmaker}) "
                f"[score={best_score:.1f}]"
            )

        return best_match

    def _compute_match_score(
        self,
        poly_home: str,
        poly_away: str,
        bk_event: SportEvent,
        market: PolymarketMarket,
    ) -> float:
        """Compute a matching score between Polymarket market and BK event."""
        bk_home = normalize_team_name(bk_event.home_team)
        bk_away = normalize_team_name(bk_event.away_team)

        # Direct order matching
        score_direct = (
            fuzz.token_sort_ratio(poly_home, bk_home)
            + fuzz.token_sort_ratio(poly_away, bk_away)
        ) / 2

        # Reverse order matching
        score_reverse = (
            fuzz.token_sort_ratio(poly_home, bk_away)
            + fuzz.token_sort_ratio(poly_away, bk_home)
        ) / 2

        base_score = max(score_direct, score_reverse)

        # Bonus for same sport
        if market.sport == bk_event.sport:
            base_score += 5

        # Bonus for close time match
        if market.end_date and bk_event.start_time:
            time_diff = abs(
                (market.end_date - bk_event.start_time).total_seconds()
            )
            if time_diff < timedelta(hours=6).total_seconds():
                base_score += 10
            elif time_diff < timedelta(days=1).total_seconds():
                base_score += 5

        return min(base_score, 100)

    def find_all_matches(
        self,
        markets: list[PolymarketMarket],
        bk_events: list[BookmakerOdds],
    ) -> list[tuple[PolymarketMarket, BookmakerOdds]]:
        """Find all matching pairs between markets and BK events."""
        matches: list[tuple[PolymarketMarket, BookmakerOdds]] = []

        for market in markets:
            best = self.match_market_to_events(market, bk_events)
            if best:
                market.matched_event = best.event
                matches.append((market, best))

        logger.info(
            f"Found {len(matches)} matches out of "
            f"{len(markets)} markets and {len(bk_events)} BK events"
        )
        return matches
