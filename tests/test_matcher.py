"""Tests for event matching."""

from src.arbitrage.matcher import (
    EventMatcher,
    extract_teams_from_question,
    normalize_team_name,
)
from src.models.events import (
    BookmakerOdds,
    Outcome,
    OutcomeType,
    PolymarketMarket,
    SportEvent,
    SportType,
)


def test_normalize_team_name():
    assert normalize_team_name("Los Angeles Lakers") == "los angeles lakers"
    assert normalize_team_name("  Lakers  ") == "los angeles lakers"
    assert normalize_team_name("Man Utd") == "manchester united"
    assert normalize_team_name("PSG") == "paris saint-germain"


def test_extract_teams_beat():
    result = extract_teams_from_question("Will Lakers beat Celtics?")
    assert result is not None
    home, away = result
    assert "lakers" in home or "los angeles lakers" in home
    assert "celtics" in away or "boston celtics" in away


def test_extract_teams_vs():
    result = extract_teams_from_question("Real Madrid vs Barcelona?")
    assert result is not None


def test_extract_teams_no_match():
    result = extract_teams_from_question("What color is the sky?")
    assert result is None


def test_event_matcher():
    market = PolymarketMarket(
        condition_id="test_1",
        question="Will Lakers beat Celtics?",
        sport=SportType.BASKETBALL,
        outcomes=[
            Outcome.from_probability("Yes", OutcomeType.YES, 0.6),
            Outcome.from_probability("No", OutcomeType.NO, 0.4),
        ],
    )

    bk_event = BookmakerOdds(
        bookmaker="Fonbet",
        event=SportEvent(
            event_id="fonbet_1",
            sport=SportType.BASKETBALL,
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
        ),
        outcomes=[
            Outcome.from_odds("1", OutcomeType.WIN_HOME, 1.8),
            Outcome.from_odds("2", OutcomeType.WIN_AWAY, 2.1),
        ],
    )

    matcher = EventMatcher(threshold=50)
    result = matcher.match_market_to_events(market, [bk_event])
    assert result is not None
    assert result.bookmaker == "Fonbet"
