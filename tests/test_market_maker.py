"""Tests for market making strategy module."""

from polymarket_bot.market_maker import (
    MarketMaker,
    MMPosition,
    MMStrategy,
)
from polymarket_bot.models import Market, Token


def _make_market(yes_price: float = 0.5, volume: float = 50000) -> Market:
    return Market(
        condition_id="c1", question="Test?", slug="test",
        tokens=[
            Token(token_id="yes1", outcome="Yes", price=yes_price),
            Token(token_id="no1", outcome="No", price=1 - yes_price),
        ],
        volume_24h=volume,
        liquidity=20000,
    )


def test_generate_quotes_basic():
    mm = MarketMaker()
    m = _make_market(0.5)
    quotes = mm.generate_quotes(m)
    assert quotes.bid_yes is not None
    assert quotes.ask_yes is not None
    assert quotes.bid_yes.price < quotes.ask_yes.price


def test_generate_quotes_extreme_price():
    mm = MarketMaker()
    m = _make_market(0.98)
    quotes = mm.generate_quotes(m)
    assert quotes.bid_yes is None  # too extreme


def test_select_markets():
    mm = MarketMaker()
    markets = [
        _make_market(0.5, 50000),
        _make_market(0.5, 100),   # low volume
        _make_market(0.5, 80000),
    ]
    selected = mm.select_markets(markets, min_volume=10000)
    assert len(selected) >= 1
    for m in selected:
        assert m.volume_24h >= 10000


def test_simulate_fill():
    mm = MarketMaker()
    mm.simulate_fill("test", "BUY YES", 0.5, 100)
    assert mm.positions["test"].yes_inventory == 100
    assert mm.positions["test"].realized_pnl == -50


def test_mm_position_balanced():
    pos = MMPosition(market_slug="test", yes_inventory=50, no_inventory=50)
    assert pos.is_balanced is True
    assert pos.net_exposure == 0

    pos2 = MMPosition(market_slug="test", yes_inventory=100, no_inventory=0)
    assert pos2.is_balanced is False


def test_get_summary():
    mm = MarketMaker()
    mm.simulate_fill("m1", "BUY YES", 0.5, 100)
    mm.simulate_fill("m1", "SELL YES", 0.55, 100)
    summary = mm.get_summary()
    assert summary["active_markets"] == 1
    assert summary["total_fills"] == 2
    assert summary["total_pnl"] == 5.0  # bought at 50, sold at 55


def test_strategy_defaults():
    s = MMStrategy()
    assert s.spread_pct == 0.03
    assert s.max_positions == 5
