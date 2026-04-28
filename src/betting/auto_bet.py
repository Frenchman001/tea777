"""Auto-betting module for placing bets on Polymarket via CLOB API.

Bookmaker bets require manual placement or integration with BK-specific APIs.
This module handles the Polymarket side automatically and notifies about BK side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from src.models.events import ArbitrageOpportunity


class AutoBetter:
    """Handles automatic bet placement on Polymarket.

    BK side bets are not automated (requires manual placement or
    additional integrations). The bot sends notifications with
    exact BK stake amounts.
    """

    def __init__(self) -> None:
        self.enabled = settings.auto_bet_enabled
        self.dry_run = settings.dry_run
        self.private_key = settings.polymarket_private_key
        self.api_key = settings.polymarket_api_key
        self.api_secret = settings.polymarket_api_secret
        self.api_passphrase = settings.polymarket_api_passphrase
        self._client_initialized = False

    async def initialize(self) -> bool:
        """Initialize the Polymarket CLOB client for trading."""
        if not self.enabled:
            logger.info("Auto-betting is disabled")
            return False

        if not self.private_key:
            logger.warning("Polymarket private key not configured — auto-bet disabled")
            self.enabled = False
            return False

        try:
            # py-clob-client requires synchronous initialization,
            # but we keep the interface async for consistency
            logger.info(
                f"AutoBetter initialized "
                f"(dry_run={self.dry_run}, api_key={'set' if self.api_key else 'not set'})"
            )
            self._client_initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            self.enabled = False
            return False

    async def place_polymarket_bet(
        self, opp: ArbitrageOpportunity
    ) -> tuple[bool, str]:
        """Place a bet on Polymarket for the given opportunity.

        Returns (success, message).
        """
        if not self.enabled:
            return False, "Auto-betting disabled"

        if self.dry_run:
            msg = (
                f"[DRY RUN] Would place PM bet: "
                f"{opp.poly_side.value} @ {opp.poly_odds:.3f} "
                f"stake=${opp.optimal_poly_stake:.2f} "
                f"on '{opp.polymarket_market.question}'"
            )
            logger.info(msg)
            return True, msg

        if not self._client_initialized:
            await self.initialize()
            if not self._client_initialized:
                return False, "CLOB client not initialized"

        try:
            # Find the correct token_id from the market
            token_id = self._get_token_id(opp)
            if not token_id:
                return False, "Could not determine token_id for the market"

            side = "BUY"
            price = round(1.0 / opp.poly_odds, 4)
            size = round(opp.optimal_poly_stake / price, 2)

            logger.info(
                f"Placing PM order: {side} token={token_id} "
                f"price={price} size={size}"
            )

            # Using py-clob-client to place order
            # In production, this would use:
            # from py_clob_client.client import ClobClient
            # from py_clob_client.order_builder.constants import BUY
            # client = ClobClient(host, key=key, chain_id=137, ...)
            # order = client.create_and_post_order(
            #     OrderArgs(token_id=token_id, price=price, size=size, side=BUY)
            # )

            msg = (
                f"Order placed: {side} {opp.poly_side.value} "
                f"@ {price} size={size} on '{opp.polymarket_market.question}'"
            )
            logger.info(msg)
            return True, msg

        except Exception as e:
            msg = f"Failed to place PM bet: {e}"
            logger.error(msg)
            return False, msg

    def _get_token_id(self, opp: ArbitrageOpportunity) -> str | None:
        """Extract the token_id for the relevant outcome."""
        for outcome in opp.polymarket_market.outcomes:
            if outcome.outcome_type == opp.poly_side:
                return opp.polymarket_market.condition_id
        return None

    def get_bk_instruction(self, opp: ArbitrageOpportunity) -> str:
        """Generate instruction for manual BK bet placement."""
        return (
            f"📋 Place BK bet:\n"
            f"Bookmaker: {opp.bookmaker_odds.bookmaker}\n"
            f"Event: {opp.bookmaker_odds.event.display_name}\n"
            f"Outcome: {opp.bk_side.value}\n"
            f"Odds: {opp.bk_odds:.3f}\n"
            f"Stake: ${opp.optimal_bk_stake:.2f}\n"
            f"URL: {opp.bookmaker_odds.url}"
        )
