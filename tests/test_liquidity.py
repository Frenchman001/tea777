"""Tests for liquidity verification module."""

from polymarket_bot.liquidity import LiquidityCheck, _simulate_fill
from polymarket_bot.models import Market, OrderBook, OrderBookLevel, Token


def _make_market(slug: str = "test", yes_price: float = 0.5) -> Market:
    return Market(
        condition_id="cond1",
        question="Test?",
        slug=slug,
        tokens=[
            Token(token_id="yes1", outcome="Yes", price=yes_price),
            Token(token_id="no1", outcome="No", price=1 - yes_price),
        ],
    )


def test_simulate_fill_basic():
    book = OrderBook(
        token_id="yes1",
        asks=[
            OrderBookLevel(price=0.50, size=100),
            OrderBookLevel(price=0.51, size=200),
        ],
        best_ask=0.50,
        best_bid=0.49,
        spread=0.01,
        midpoint=0.495,
    )
    result = _simulate_fill(book, 25.0, "test", "YES")
    assert result.fillable is True
    assert result.slippage_pct >= 0
    assert result.levels_consumed >= 1


def test_simulate_fill_insufficient_depth():
    book = OrderBook(
        token_id="yes1",
        asks=[OrderBookLevel(price=0.50, size=10)],
        best_ask=0.50,
        best_bid=0.49,
        spread=0.01,
        midpoint=0.495,
    )
    result = _simulate_fill(book, 100.0, "test", "YES")
    assert result.fillable is False


def test_simulate_fill_empty_book():
    book = OrderBook(
        token_id="yes1", asks=[], bids=[],
        best_ask=1.0, best_bid=0.0, spread=1.0, midpoint=0.5,
    )
    result = _simulate_fill(book, 50.0, "test", "YES")
    assert result.fillable is False
    assert result.slippage_pct == 100.0


def test_liquidity_check_is_safe():
    safe = LiquidityCheck(
        market_slug="test", side="YES",
        recommended_bet_usd=50, available_depth_usd=100,
        fillable=True, avg_fill_price=0.5, slippage_pct=1.0,
        levels_consumed=2,
    )
    assert safe.is_safe is True

    unsafe = LiquidityCheck(
        market_slug="test", side="YES",
        recommended_bet_usd=50, available_depth_usd=20,
        fillable=False, avg_fill_price=0.5, slippage_pct=5.0,
        levels_consumed=1,
    )
    assert unsafe.is_safe is False


def test_simulate_fill_multi_level():
    book = OrderBook(
        token_id="yes1",
        asks=[
            OrderBookLevel(price=0.50, size=20),
            OrderBookLevel(price=0.52, size=50),
            OrderBookLevel(price=0.55, size=100),
        ],
        best_ask=0.50,
        best_bid=0.49,
        spread=0.01,
        midpoint=0.495,
    )
    result = _simulate_fill(book, 30.0, "test", "YES")
    assert result.fillable is True
    assert result.levels_consumed >= 2
    assert result.avg_fill_price > 0.50
