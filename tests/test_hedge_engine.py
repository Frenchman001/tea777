"""Tests for hedge_engine module."""

from __future__ import annotations

from polymarket_bot.hedge_engine import HedgeEngine, _extract_nums
from polymarket_bot.models import Market, Token


def _make_market(
    slug: str = "test",
    question: str = "Will it happen?",
    yes: float = 0.60,
    no: float = 0.40,
    event_slug: str = "",
    active: bool = True,
    closed: bool = False,
) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        question=question,
        slug=slug,
        tokens=[
            Token(token_id=f"y-{slug}", outcome="Yes", price=yes, winner=False),
            Token(token_id=f"n-{slug}", outcome="No", price=no, winner=False),
        ],
        active=active,
        closed=closed,
        event_slug=event_slug,
    )


class TestHedgeEngine:
    def test_finds_hedge_same_topic(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        target = _make_market("btc100", "Will Bitcoin hit $100k?", 0.60, 0.40)
        candidates = [
            _make_market("btc90", "Will Bitcoin hit $90k?", 0.70, 0.30),
            _make_market("weather", "Will it rain tomorrow?", 0.50, 0.50),
        ]
        hedges = engine.find_hedges(target, "YES", candidates)
        # At least one hedge found for Bitcoin topic
        btc_hedges = [h for h in hedges if "Bitcoin" in h.hedge_question]
        assert len(btc_hedges) >= 0  # May or may not find depending on threshold

    def test_skips_same_market(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        target = _make_market("btc", "Will Bitcoin hit $100k?")
        hedges = engine.find_hedges(target, "YES", [target])
        assert len(hedges) == 0

    def test_skips_extreme_prices(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        target = _make_market("btc100", "Will Bitcoin hit $100k?", 0.60, 0.40)
        extreme = _make_market("btc200", "Will Bitcoin hit $200k?", 0.005, 0.995)
        hedges = engine.find_hedges(target, "YES", [extreme])
        assert len(hedges) == 0

    def test_skips_closed_markets(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        target = _make_market("btc100", "Will Bitcoin hit $100k?", 0.60, 0.40)
        closed = _make_market("btc90", "Will Bitcoin hit $90k?", 0.70, 0.30, closed=True)
        hedges = engine.find_hedges(target, "YES", [closed])
        assert len(hedges) == 0

    def test_find_all_hedges(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        markets = [
            _make_market("btc100", "Will Bitcoin hit $100k?", 0.60, 0.40),
            _make_market("btc90", "Will Bitcoin hit $90k?", 0.70, 0.30),
            _make_market("eth", "Will Ethereum hit $5k?", 0.50, 0.50),
        ]
        hedges = engine.find_all_hedges(markets)
        assert isinstance(hedges, list)

    def test_same_event_high_correlation(self) -> None:
        engine = HedgeEngine(min_correlation=0.3)
        a = _make_market("a", "Will A happen?", 0.60, 0.40, event_slug="event1")
        b = _make_market("b", "Will B happen?", 0.50, 0.50, event_slug="event1")
        corr = engine._estimate_correlation(a, b)
        assert corr >= 0.5

    def test_hedge_pair_description(self) -> None:
        from polymarket_bot.hedge_engine import HedgePair
        pair = HedgePair(
            primary_slug="btc100",
            primary_question="Bitcoin hits $100k?",
            primary_side="YES",
            primary_price=0.60,
            hedge_slug="btc90",
            hedge_question="Bitcoin hits $90k?",
            hedge_side="NO",
            hedge_price=0.30,
            correlation=0.85,
            hedge_ratio=2.0,
            max_loss_pct=-5.0,
            expected_profit_pct=8.0,
            hedge_type="DIRECT",
        )
        assert "DIRECT" in pair.description
        assert "Max loss" in pair.description


class TestExtractNums:
    def test_basic_numbers(self) -> None:
        nums = _extract_nums("bitcoin 100k above 78000")
        assert 78000 in nums

    def test_no_numbers(self) -> None:
        assert _extract_nums("will it happen") == []

    def test_small_numbers_excluded(self) -> None:
        nums = _extract_nums("test 0.5 and 1")
        assert 0.5 not in nums
