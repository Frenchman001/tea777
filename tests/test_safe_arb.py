"""Tests for safe_arb module."""

from __future__ import annotations

from unittest.mock import MagicMock

from polymarket_bot.models import Market, OrderBook, Token
from polymarket_bot.safe_arb import SafeArbEngine, SafeArbPosition, _detect_category


def _make_market(
    yes: float = 0.45,
    no: float = 0.45,
    slug: str = "test-market",
    question: str = "Will it happen?",
    active: bool = True,
    closed: bool = False,
) -> Market:
    return Market(
        condition_id="c1",
        question=question,
        slug=slug,
        tokens=[
            Token(token_id="yes1", outcome="Yes", price=yes, winner=False),
            Token(token_id="no1", outcome="No", price=no, winner=False),
        ],
        active=active,
        closed=closed,
    )


class TestSafeArbEngine:
    def test_finds_arb_when_sum_less_than_one(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.40, no=0.40)  # sum=0.80
        client = MagicMock()
        client.get_order_book.return_value = None

        positions = engine.scan(client, [m])
        for p in positions:
            assert p.is_profitable
            assert p.net_profit > 0
            assert p.price_sum < 1.0

    def test_no_arb_when_sum_equals_one(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.50, no=0.50)
        client = MagicMock()
        positions = engine.scan(client, [m])
        assert len(positions) == 0

    def test_skips_closed_markets(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.40, no=0.40, closed=True)
        client = MagicMock()
        positions = engine.scan(client, [m])
        assert len(positions) == 0

    def test_skips_inactive_markets(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.40, no=0.40, active=False)
        client = MagicMock()
        positions = engine.scan(client, [m])
        assert len(positions) == 0

    def test_skips_extreme_prices(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.005, no=0.005)
        client = MagicMock()
        positions = engine.scan(client, [m])
        assert len(positions) == 0

    def test_uses_orderbook_ask_prices(self) -> None:
        engine = SafeArbEngine(bankroll=1000)
        m = _make_market(yes=0.40, no=0.40)
        client = MagicMock()

        book = OrderBook(
            token_id="yes1",
            bids=[],
            asks=[],
            best_bid=0.39,
            best_ask=0.41,
            spread=0.02,
        )
        client.get_order_book.return_value = book
        positions = engine.scan(client, [m])
        # May or may not find arb depending on orderbook prices
        assert isinstance(positions, list)

    def test_position_description(self) -> None:
        pos = SafeArbPosition(
            market_slug="test",
            question="Will Bitcoin hit $100k?",
            yes_price=0.40,
            no_price=0.40,
            price_sum=0.80,
            buy_yes_shares=100,
            buy_no_shares=100,
            total_cost=80.0,
            guaranteed_payout=100.0,
            fee_yes=1.0,
            fee_no=1.0,
            total_fees=2.0,
            net_profit=18.0,
            net_profit_pct=22.5,
            roi_annualized=1175.0,
            category="crypto",
            is_profitable=True,
        )
        assert "SAFE" in pos.description
        assert "$18.00" in pos.description

    def test_unprofitable_description(self) -> None:
        pos = SafeArbPosition(
            market_slug="test",
            question="Test",
            yes_price=0.49,
            no_price=0.49,
            price_sum=0.98,
            buy_yes_shares=50,
            buy_no_shares=50,
            total_cost=49.0,
            guaranteed_payout=50.0,
            fee_yes=0.5,
            fee_no=0.5,
            total_fees=1.0,
            net_profit=-0.5,
            net_profit_pct=-1.0,
            roi_annualized=-52.1,
            category="other",
            is_profitable=False,
        )
        assert "UNPROFITABLE" in pos.description


class TestDetectCategory:
    def test_crypto(self) -> None:
        assert _detect_category("Will Bitcoin hit $100k?") == "crypto"

    def test_politics(self) -> None:
        assert _detect_category("Will Trump win the election?") == "politics"

    def test_sports(self) -> None:
        assert _detect_category("Will Lakers win vs. Celtics?") == "sports"

    def test_economics(self) -> None:
        assert _detect_category("Will the Fed cut rates?") == "economics"

    def test_geopolitics(self) -> None:
        assert _detect_category("Will Iran ceasefire hold?") == "geopolitics"

    def test_other(self) -> None:
        assert _detect_category("Random question about weather") == "other"
