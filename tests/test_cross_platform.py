"""Tests for cross-platform arbitrage module."""

from polymarket_bot.cross_platform import (
    CrossPlatformArb,
    CrossPlatformScanner,
    ExternalMarket,
    _normalize,
    _question_similarity,
)
from polymarket_bot.models import Market, Token


def _make_market(question: str, yes_price: float, slug: str = "test") -> Market:
    return Market(
        condition_id="c1", question=question, slug=slug,
        tokens=[
            Token(token_id="y1", outcome="Yes", price=yes_price),
            Token(token_id="n1", outcome="No", price=1 - yes_price),
        ],
    )


def test_question_similarity_identical():
    sim = _question_similarity("Will Bitcoin hit $100k?", "Will Bitcoin hit $100k?")
    assert sim == 1.0


def test_question_similarity_different():
    sim = _question_similarity("Will it rain?", "Bitcoin price prediction")
    assert sim < 0.3


def test_question_similarity_similar():
    sim = _question_similarity(
        "Will Bitcoin reach $100,000 by December?",
        "Will Bitcoin reach $100k by end of year?",
    )
    assert sim > 0.4


def test_normalize():
    assert _normalize("Hello, World!  Test") == "hello world test"


def test_find_internal_cross_arb():
    markets = [
        _make_market("Will Bitcoin reach $100k?", 0.6, "btc1"),
        _make_market("Will Bitcoin reach $100k by Dec?", 0.75, "btc2"),
        _make_market("Will it rain tomorrow?", 0.3, "rain"),
    ]
    scanner = CrossPlatformScanner()
    try:
        arbs = scanner.find_internal_cross_arb(markets, min_diff=0.05)
        assert isinstance(arbs, list)
        for arb in arbs:
            assert arb.price_diff >= 0.05
    finally:
        scanner.close()


def test_external_market_dataclass():
    em = ExternalMarket(
        platform="Kalshi",
        title="Will X happen?",
        yes_price=0.6,
        no_price=0.4,
        url="https://kalshi.com/test",
    )
    assert em.platform == "Kalshi"
    assert em.yes_price == 0.6


def test_cross_arb_description():
    m = _make_market("Bitcoin $100k?", 0.5)
    arb = CrossPlatformArb(
        polymarket=m,
        external=ExternalMarket("Kalshi", "BTC 100k", 0.7, 0.3),
        poly_yes=0.5, ext_yes=0.7, price_diff=0.2,
        arb_type="BUY_POLY",
        recommended_action="test",
        estimated_profit_pct=20.0,
    )
    desc = arb.description
    assert "CROSS-ARB" in desc
    assert "20.0%" in desc
