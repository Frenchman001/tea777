"""Tests for bug fixes: backtest winner detection and cross-arb false positive filter."""

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.cross_platform import _extract_numbers, _question_similarity

# --- Fix 1: Backtest winner detection from closed market prices ---

def test_parse_market_winner_detection():
    """Closed market with price=1.0 should have winner=True."""
    client = PolymarketClient()
    market = client._parse_market({
        "conditionId": "c1",
        "question": "Lakers vs Rockets",
        "slug": "lakers-rockets",
        "outcomes": '["Lakers", "Rockets"]',
        "outcomePrices": '["0", "1"]',
        "clobTokenIds": '["t1", "t2"]',
        "closed": True,
        "active": True,
    })
    client.close()

    winners = [t for t in market.tokens if t.winner]
    assert len(winners) == 1
    assert winners[0].outcome == "Rockets"
    assert winners[0].price >= 0.99


def test_parse_market_open_no_winner():
    """Open market should not have any winners."""
    client = PolymarketClient()
    market = client._parse_market({
        "conditionId": "c2",
        "question": "Test?",
        "slug": "test",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.6", "0.4"]',
        "clobTokenIds": '["t1", "t2"]',
        "closed": False,
    })
    client.close()

    winners = [t for t in market.tokens if t.winner]
    assert len(winners) == 0


def test_parse_market_closed_mid_price():
    """Closed market with mid-range prices should not declare winners."""
    client = PolymarketClient()
    market = client._parse_market({
        "conditionId": "c3",
        "question": "Test?",
        "slug": "test",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.7", "0.3"]',
        "clobTokenIds": '["t1", "t2"]',
        "closed": True,
    })
    client.close()

    winners = [t for t in market.tokens if t.winner]
    assert len(winners) == 0


# --- Fix 2: Cross-arb false positive filter ---

def test_extract_numbers_basic():
    assert _extract_numbers("Bitcoin above $78,000") == [78000.0]
    assert _extract_numbers("Will hit $150k") == [150000.0]
    assert _extract_numbers("GDP growth of 3.5%") == [3.5]


def test_extract_numbers_multiple():
    nums = _extract_numbers("Price between $70,000 and $80,000")
    assert 70000.0 in nums
    assert 80000.0 in nums


def test_similarity_different_strike_prices():
    """Markets with same text but different numbers should NOT match."""
    sim = _question_similarity(
        "Will the price of Bitcoin be above $78,000?",
        "Will the price of Bitcoin be above $72,000?",
    )
    assert sim == 0.0, f"Expected 0.0 for different strikes, got {sim}"


def test_similarity_same_numbers():
    """Markets with same numbers should still match normally."""
    sim = _question_similarity(
        "Will Bitcoin hit $100k by December 2026?",
        "Will Bitcoin hit $100k by December 2026?",
    )
    assert sim > 0.9


def test_similarity_different_topics():
    """Completely different markets should have low similarity."""
    sim = _question_similarity(
        "Will Bitcoin hit $100k?",
        "Will Lakers win the NBA championship?",
    )
    assert sim < 0.5


def test_similarity_fed_rate_different():
    """Fed rate markets with different key words still have high text similarity."""
    sim = _question_similarity(
        "Will the Fed increase interest rates?",
        "Will the Fed decrease interest rates?",
    )
    # These differ by one word, so similarity is high — this is expected
    assert sim > 0.5
