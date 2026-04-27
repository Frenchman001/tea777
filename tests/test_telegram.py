"""Tests for Telegram notification module."""

from polymarket_bot.smart_alerts import Alert, AlertPriority, AlertSummary
from polymarket_bot.telegram_alerts import (
    TelegramNotifier,
    _escape_html,
    _priority_emoji,
)


def test_not_configured():
    tg = TelegramNotifier(bot_token="", chat_id="")
    assert tg.is_configured is False
    result = tg.send_message("test")
    assert result is False
    tg.close()


def test_is_configured():
    tg = TelegramNotifier(bot_token="123:ABC", chat_id="456")
    assert tg.is_configured is True
    tg.close()


def test_escape_html():
    assert _escape_html("<b>test&</b>") == "&lt;b&gt;test&amp;&lt;/b&gt;"


def test_priority_emoji():
    assert _priority_emoji(AlertPriority.CRITICAL) != ""
    assert _priority_emoji(AlertPriority.LOW) != ""


def test_send_alert_unconfigured():
    tg = TelegramNotifier(bot_token="", chat_id="")
    alert = Alert(
        priority=AlertPriority.HIGH,
        alert_type="SIGNAL",
        title="Test",
        market_question="Test?",
        expected_profit_usd=5.0,
        recommended_bet_usd=50,
        confidence=0.7,
        details="test",
        market_slug="test",
    )
    result = tg.send_alert(alert)
    assert result is False
    tg.close()


def test_send_summary_unconfigured():
    tg = TelegramNotifier(bot_token="", chat_id="")
    summary = AlertSummary(alerts=[], total_expected_profit=0)
    result = tg.send_summary(summary)
    assert result is False
    tg.close()
