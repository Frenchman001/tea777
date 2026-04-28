"""Telegram bot for arbitrage alerts and management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from src.models.events import ArbitrageOpportunity


class ArbitrageBot:
    """Telegram bot that sends arbitrage alerts and handles commands."""

    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram bot token or chat_id not configured")
            return False

        session = await self._get_session()
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return True
                body = await resp.text()
                logger.error(f"Telegram API error {resp.status}: {body}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

        return False

    async def send_arbitrage_alert(self, opp: ArbitrageOpportunity) -> bool:
        """Send a formatted arbitrage alert."""
        text = self._format_alert(opp)
        return await self.send_message(text)

    async def send_scan_summary(
        self,
        opportunities: list[ArbitrageOpportunity],
        total_markets: int,
        total_bk_events: int,
        matched_pairs: int,
    ) -> bool:
        """Send a summary of a scan cycle."""
        if opportunities:
            text = (
                f"📊 <b>Scan Complete</b>\n\n"
                f"Markets scanned: {total_markets}\n"
                f"BK events: {total_bk_events}\n"
                f"Matched pairs: {matched_pairs}\n"
                f"🔥 <b>Arbitrage found: {len(opportunities)}</b>\n\n"
            )
            for i, opp in enumerate(opportunities[:10], 1):
                text += f"<b>#{i}</b>\n{self._format_alert(opp)}\n\n"
        else:
            text = (
                f"📊 <b>Scan Complete</b>\n\n"
                f"Markets: {total_markets} | BK events: {total_bk_events}\n"
                f"Matched: {matched_pairs}\n"
                f"❌ No arbitrage opportunities found this cycle."
            )

        return await self.send_message(text)

    async def send_bet_confirmation(
        self,
        opp: ArbitrageOpportunity,
        poly_success: bool,
        bk_note: str = "",
    ) -> bool:
        """Send a bet placement confirmation."""
        poly_status = "✅" if poly_success else "❌"
        text = (
            f"🎰 <b>Bet Placed</b>\n\n"
            f"Event: {opp.polymarket_market.question}\n"
            f"PM stake: ${opp.optimal_poly_stake:.2f} {poly_status}\n"
            f"BK stake: ${opp.optimal_bk_stake:.2f} ({opp.bookmaker_odds.bookmaker})\n"
            f"Expected profit: ${opp.guaranteed_profit:.2f}\n"
        )
        if bk_note:
            text += f"\n⚠️ BK Note: {bk_note}"

        return await self.send_message(text)

    async def send_error(self, error_msg: str) -> bool:
        """Send an error notification."""
        text = f"⚠️ <b>Error</b>\n\n{error_msg}"
        return await self.send_message(text)

    async def send_startup(self) -> bool:
        """Send a startup notification."""
        text = (
            "🚀 <b>Polymarket Arbitrage Bot Started</b>\n\n"
            f"Scan interval: {settings.scan_interval_seconds}s\n"
            f"Min profit: {settings.min_profit_percent}%\n"
            f"Max stake: ${settings.max_stake_usd}\n"
            f"Auto-bet: {'ON' if settings.auto_bet_enabled else 'OFF'}\n"
            f"Dry run: {'YES' if settings.dry_run else 'NO'}\n\n"
            "Bookmakers: Fonbet, Winline, 1xBet"
        )
        return await self.send_message(text)

    @staticmethod
    def _format_alert(opp: ArbitrageOpportunity) -> str:
        """Format an arbitrage opportunity as HTML."""
        return (
            f"🔥 <b>{opp.polymarket_market.question}</b>\n"
            f"📈 Polymarket [{opp.poly_side.value}]: "
            f"<code>{opp.poly_odds:.3f}</code>\n"
            f"🏢 {opp.bookmaker_odds.bookmaker} [{opp.bk_side.value}]: "
            f"<code>{opp.bk_odds:.3f}</code>\n"
            f"💰 Profit: <b>{opp.profit_percent:.2f}%</b>\n"
            f"💵 PM=${opp.optimal_poly_stake:.2f} + "
            f"BK=${opp.optimal_bk_stake:.2f}\n"
            f"✅ Guaranteed: <b>${opp.guaranteed_profit:.2f}</b>"
        )
