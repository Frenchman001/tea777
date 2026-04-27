"""Tests for auto-trader module."""

from polymarket_bot.auto_trader import (
    AutoTrader,
    OrderSide,
    OrderStatus,
    TradeOrder,
    TradingSession,
)
from polymarket_bot.config import Config
from polymarket_bot.liquidity import LiquidityCheck
from polymarket_bot.smart_alerts import Alert, AlertPriority


def _make_alert(bet: float = 50.0) -> Alert:
    return Alert(
        priority=AlertPriority.HIGH,
        alert_type="SIGNAL",
        title="Test",
        market_question="Test?",
        expected_profit_usd=5.0,
        recommended_bet_usd=bet,
        confidence=0.7,
        details="test",
        market_slug="test",
    )


def test_dry_run_mode():
    config = Config()
    trader = AutoTrader(config)
    trader.initialize()
    assert trader._dry_run is True

    alert = _make_alert()
    liq = LiquidityCheck(
        market_slug="test", side="YES",
        recommended_bet_usd=50, available_depth_usd=200,
        fillable=True, avg_fill_price=0.5, slippage_pct=0.5,
        levels_consumed=2,
    )
    result = trader.execute_alert(alert, liquidity=liq, token_id="yes1")
    assert result.success is True
    assert "DRY RUN" in result.message


def test_reject_insufficient_liquidity():
    config = Config()
    trader = AutoTrader(config)
    trader.initialize()

    alert = _make_alert()
    bad_liq = LiquidityCheck(
        market_slug="test", side="YES",
        recommended_bet_usd=50, available_depth_usd=10,
        fillable=False, avg_fill_price=0.5, slippage_pct=10.0,
        levels_consumed=1,
    )
    result = trader.execute_alert(alert, liquidity=bad_liq, token_id="yes1")
    assert result.success is False
    assert "liquidity" in result.message.lower()


def test_session_summary():
    config = Config()
    trader = AutoTrader(config)
    trader.initialize()

    alert = _make_alert()
    liq = LiquidityCheck(
        market_slug="test", side="YES",
        recommended_bet_usd=50, available_depth_usd=200,
        fillable=True, avg_fill_price=0.5, slippage_pct=0.5,
        levels_consumed=2,
    )
    trader.execute_alert(alert, liquidity=liq, token_id="yes1")

    summary = trader.get_session_summary()
    assert summary["mode"] == "DRY RUN"
    assert summary["total_orders"] == 1


def test_trade_order_cost():
    order = TradeOrder(
        market_slug="test", token_id="yes1",
        side=OrderSide.BUY, price=0.5, size=100,
    )
    assert order.cost_usd == 50.0


def test_trading_session_num_trades():
    session = TradingSession()
    session.orders.append(TradeOrder(
        market_slug="s", token_id="t",
        side=OrderSide.BUY, price=0.5, size=10,
        status=OrderStatus.FILLED,
    ))
    session.orders.append(TradeOrder(
        market_slug="s2", token_id="t2",
        side=OrderSide.BUY, price=0.5, size=10,
        status=OrderStatus.FAILED,
    ))
    assert session.num_trades == 1
