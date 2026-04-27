"""Decay Harvester — finds low-probability markets near expiration for near-risk-free profit.

Like options theta decay: markets priced at 1-8% with <14 days to expiry
rarely resolve YES. Selling YES (buying NO) at $0.92-0.99 yields
guaranteed near-free money when the event doesn't happen.

Annualized returns of 30-200% are common on these "time decay" positions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from polymarket_bot.models import Market
from polymarket_bot.profit_engine import calculate_fee

logger = logging.getLogger(__name__)


@dataclass
class DecayOpportunity:
    market_slug: str
    question: str
    yes_price: float
    no_price: float
    days_to_expiry: float
    annualized_return_pct: float
    profit_per_dollar: float
    recommended_bet_usd: float
    recommended_side: str
    risk_level: str  # LOW, MEDIUM, HIGH
    category: str
    confidence: float

    @property
    def description(self) -> str:
        return (
            f"[DECAY] {self.question[:45]} | "
            f"YES={self.yes_price:.0%} | {self.days_to_expiry:.0f}d left | "
            f"Return: {self.annualized_return_pct:.0f}%/yr | "
            f"Risk: {self.risk_level}"
        )


class DecayHarvester:
    """Finds time-decay opportunities in low-probability markets."""

    def __init__(
        self,
        max_yes_price: float = 0.08,
        min_no_price: float = 0.90,
        max_days: float = 14.0,
        min_days: float = 0.5,
        min_volume: float = 1000.0,
        bankroll: float = 1000.0,
    ) -> None:
        self.max_yes_price = max_yes_price
        self.min_no_price = min_no_price
        self.max_days = max_days
        self.min_days = min_days
        self.min_volume = min_volume
        self.bankroll = bankroll

    def scan(self, markets: list[Market]) -> list[DecayOpportunity]:
        """Find decay opportunities in market list."""
        opportunities: list[DecayOpportunity] = []

        now = datetime.now(tz=timezone.utc)

        for market in markets:
            if not market.active or market.closed:
                continue

            if not market.end_date:
                continue

            try:
                end_dt = datetime.fromisoformat(
                    market.end_date.replace("Z", "+00:00"),
                )
            except (ValueError, TypeError):
                continue

            days_left = (end_dt - now).total_seconds() / 86400
            if days_left < self.min_days or days_left > self.max_days:
                continue

            yes_price = market.yes_price
            no_price = market.no_price

            opp = self._evaluate_low_yes(market, yes_price, days_left)
            if opp:
                opportunities.append(opp)
                continue

            opp = self._evaluate_high_yes(market, yes_price, no_price, days_left)
            if opp:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.annualized_return_pct, reverse=True)
        return opportunities

    def _evaluate_low_yes(
        self,
        market: Market,
        yes_price: float,
        days_left: float,
    ) -> DecayOpportunity | None:
        """YES is cheap (1-8%) near expiry → buy NO, collect when it resolves NO."""
        if yes_price > self.max_yes_price or yes_price <= 0.005:
            return None

        no_price = 1.0 - yes_price
        if no_price < self.min_no_price:
            return None

        profit_per_dollar = (1.0 - no_price) / no_price
        annualized = profit_per_dollar * (365 / max(days_left, 0.5)) * 100

        fee = calculate_fee(no_price, 100, "other")
        net_profit = profit_per_dollar - fee.effective_fee_pct / 100

        if net_profit <= 0:
            return None

        risk = self._assess_risk(yes_price, days_left, market.volume_24h)
        max_bet = self.bankroll * 0.05
        bet = min(max_bet, market.liquidity * 0.1) if market.liquidity > 0 else max_bet

        return DecayOpportunity(
            market_slug=market.slug,
            question=market.question,
            yes_price=yes_price,
            no_price=no_price,
            days_to_expiry=days_left,
            annualized_return_pct=annualized,
            profit_per_dollar=round(net_profit, 4),
            recommended_bet_usd=round(bet, 2),
            recommended_side="BUY_NO",
            risk_level=risk,
            category=_guess_simple_category(market.question),
            confidence=self._decay_confidence(yes_price, days_left),
        )

    def _evaluate_high_yes(
        self,
        market: Market,
        yes_price: float,
        no_price: float,
        days_left: float,
    ) -> DecayOpportunity | None:
        """YES is expensive (92-99%) near expiry → buy YES, collect when it resolves YES."""
        if yes_price < (1.0 - self.max_yes_price) or yes_price >= 0.995:
            return None

        if no_price > self.max_yes_price or no_price <= 0.005:
            pass
        else:
            return None

        profit_per_dollar = (1.0 - yes_price) / yes_price
        annualized = profit_per_dollar * (365 / max(days_left, 0.5)) * 100

        fee = calculate_fee(yes_price, 100, "other")
        net_profit = profit_per_dollar - fee.effective_fee_pct / 100

        if net_profit <= 0:
            return None

        risk = self._assess_risk(no_price, days_left, market.volume_24h)
        max_bet = self.bankroll * 0.05
        bet = min(max_bet, market.liquidity * 0.1) if market.liquidity > 0 else max_bet

        return DecayOpportunity(
            market_slug=market.slug,
            question=market.question,
            yes_price=yes_price,
            no_price=no_price,
            days_to_expiry=days_left,
            annualized_return_pct=annualized,
            profit_per_dollar=round(net_profit, 4),
            recommended_bet_usd=round(bet, 2),
            recommended_side="BUY_YES",
            risk_level=risk,
            category=_guess_simple_category(market.question),
            confidence=self._decay_confidence(no_price, days_left),
        )

    def _assess_risk(
        self, unlikely_price: float, days: float, volume: float,
    ) -> str:
        if unlikely_price <= 0.02 and days <= 3 and volume > 5000:
            return "LOW"
        if unlikely_price <= 0.05 and days <= 7:
            return "MEDIUM"
        return "HIGH"

    def _decay_confidence(self, unlikely_price: float, days: float) -> float:
        price_conf = max(0, 1.0 - unlikely_price * 10)
        time_conf = max(0, 1.0 - days / 30)
        return round(min(price_conf * 0.6 + time_conf * 0.4, 0.95), 2)


def _guess_simple_category(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["bitcoin", "ethereum", "crypto", "btc", "eth", "price"]):
        return "crypto"
    if any(w in q for w in ["trump", "election", "president", "vote", "congress"]):
        return "politics"
    if any(w in q for w in ["nba", "nfl", "fifa", "win", "vs.", "match"]):
        return "sports"
    return "other"
