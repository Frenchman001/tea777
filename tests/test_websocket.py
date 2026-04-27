"""Tests for WebSocket price stream module."""

from polymarket_bot.models import Market, Token
from polymarket_bot.websocket_stream import (
    PriceStreamManager,
    create_price_monitor,
)


def test_register_market():
    manager = PriceStreamManager()
    manager.register_market("btc-100k", "Bitcoin $100k?", "yes1", "no1")
    assert "btc-100k" in manager._market_tokens


def test_update_price_no_arb():
    manager = PriceStreamManager()
    manager.register_market("btc-100k", "Bitcoin $100k?", "yes1", "no1")
    manager.update_price("yes1", 0.60)
    manager.update_price("no1", 0.42)
    # Sum = 1.02, no arb
    assert len(manager.get_recent_alerts()) == 0


def test_update_price_triggers_arb():
    manager = PriceStreamManager()
    alerts_received = []
    manager.on_alert(lambda a: alerts_received.append(a))
    manager.register_market("btc-100k", "Bitcoin $100k?", "yes1", "no1")
    manager.update_price("yes1", 0.45)
    manager.update_price("no1", 0.45)
    # Sum = 0.90, arb!
    assert len(alerts_received) == 1
    assert alerts_received[0].profit_pct > 0


def test_create_price_monitor():
    markets = [
        Market(
            condition_id="c1", question="Test?", slug="test",
            tokens=[
                Token(token_id="yes1", outcome="Yes", price=0.5),
                Token(token_id="no1", outcome="No", price=0.5),
            ],
        ),
    ]
    monitor = create_price_monitor(markets)
    assert len(monitor._market_tokens) == 1


def test_stop_polling():
    manager = PriceStreamManager()
    manager.stop()
    assert manager._running is False


def test_get_recent_alerts_empty():
    manager = PriceStreamManager()
    assert manager.get_recent_alerts() == []
