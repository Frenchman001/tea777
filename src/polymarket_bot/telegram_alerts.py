"""Telegram bot for push notifications of trading alerts.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
Create a bot via @BotFather on Telegram.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from polymarket_bot.smart_alerts import Alert, AlertPriority, AlertSummary

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    """Sends trading alerts to Telegram."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._http = httpx.Client(timeout=10.0)
        self._last_send_time = 0.0
        self._min_interval = 2.0

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def close(self) -> None:
        self._http.close()

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat."""
        if not self.is_configured:
            logger.warning("Telegram not configured (missing token or chat_id)")
            return False

        elapsed = time.time() - self._last_send_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        try:
            resp = self._http.post(
                f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            resp.raise_for_status()
            self._last_send_time = time.time()
            return True
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            return False

    def send_alert(self, alert: Alert) -> bool:
        """Send a single alert as a formatted Telegram message."""
        emoji = _priority_emoji(alert.priority)
        text = (
            f"{emoji} <b>{alert.alert_type}</b>\n"
            f"📊 {_escape_html(alert.market_question[:80])}\n"
            f"💰 Profit: <b>${alert.expected_profit_usd:.2f}</b>\n"
            f"🎯 Bet: ${alert.recommended_bet_usd:.2f} | "
            f"Confidence: {alert.confidence:.0%}\n"
            f"⚠️ Risk: {alert.risk_level}\n"
            f"📝 {_escape_html(alert.details[:100])}"
        )
        return self.send_message(text)

    def send_summary(self, summary: AlertSummary) -> bool:
        """Send a summary of all alerts."""
        if not summary.alerts:
            return self.send_message("📭 No alerts found in this scan.")

        stats = summary.scan_stats
        text = (
            f"📊 <b>Polymarket Scan Results</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 Markets scanned: {stats.get('markets_scanned', 0)}\n"
            f"🎯 Total alerts: <b>{stats.get('total_alerts', 0)}</b>\n"
            f"  • Arbitrage: {stats.get('arbitrage_alerts', 0)}\n"
            f"  • Signals: {stats.get('signal_alerts', 0)}\n"
            f"  • Correlations: {stats.get('correlation_alerts', 0)}\n"
            f"💰 Expected profit: <b>${summary.total_expected_profit:.2f}</b>\n"
        )

        if summary.best_opportunity:
            best = summary.best_opportunity
            text += (
                f"\n🏆 <b>Best opportunity:</b>\n"
                f"{_escape_html(best.market_question[:80])}\n"
                f"${best.expected_profit_usd:.2f} profit | "
                f"{best.confidence:.0%} confidence"
            )

        return self.send_message(text)

    def send_top_alerts(
        self, alerts: list[Alert], max_alerts: int = 5,
    ) -> int:
        """Send the top N alerts individually. Returns count sent."""
        sent = 0
        for alert in alerts[:max_alerts]:
            if self.send_alert(alert):
                sent += 1
        return sent


def _priority_emoji(priority: AlertPriority) -> str:
    return {
        AlertPriority.CRITICAL: "🔴",
        AlertPriority.HIGH: "🟠",
        AlertPriority.MEDIUM: "🟡",
        AlertPriority.LOW: "🟢",
    }.get(priority, "⚪")


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
