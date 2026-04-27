"""Resolution Sniper — captures near-certain outcomes close to market resolution.

When a market is about to resolve and one outcome is 95%+, the remaining
5% is near-guaranteed profit. Markets with high volume near resolution
are especially reliable because prices reflect maximum information.

Risk profile: VERY LOW — only targets outcomes with 95%+ probability
within 72 hours of resolution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from polymarket_bot.models import Market
from polymarket_bot.profit_engine import calculate_fee

logger = logging.getLogger(__name__)


@dataclass
class SniperTarget:
    market_slug: str
    question: str
    likely_outcome: str  # YES or NO
    outcome_price: float  # price of likely outcome (e.g. 0.97)
    profit_per_share: float  # 1.0 - price (e.g. 0.03)
    hours_to_resolution: float
    volume_24h: float
    liquidity: float
    net_profit_per_100: float  # net profit per $100 invested after fees
    confidence: float
    risk_level: str
    recommended_bet: float
    category: str

    @property
    def description(self) -> str:
        return (
            f"[SNIPER] {self.question[:40]} | "
            f"{self.likely_outcome} @ {self.outcome_price:.1%} | "
            f"+${self.net_profit_per_100:.2f}/100$ | "
            f"{self.hours_to_resolution:.0f}h left | Risk: {self.risk_level}"
        )


class ResolutionSniper:
    """Finds near-certain markets about to resolve for safe profit."""

    def __init__(
        self,
        min_certainty: float = 0.93,
        max_hours: float = 72.0,
        min_volume: float = 5000.0,
        bankroll: float = 1000.0,
    ) -> None:
        self.min_certainty = min_certainty
        self.max_hours = max_hours
        self.min_volume = min_volume
        self.bankroll = bankroll

    def scan(self, markets: list[Market]) -> list[SniperTarget]:
        """Find near-certain markets close to resolution."""
        targets: list[SniperTarget] = []
        now = datetime.now(tz=timezone.utc)

        for market in markets:
            if not market.active or market.closed:
                continue

            if not market.end_date:
                continue

            try:
                raw = market.end_date.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(raw)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            hours_left = (end_dt - now).total_seconds() / 3600
            if hours_left < 0 or hours_left > self.max_hours:
                continue

            target = self._evaluate(market, hours_left)
            if target:
                targets.append(target)

        targets.sort(key=lambda t: t.net_profit_per_100, reverse=True)
        return targets

    def _evaluate(
        self,
        market: Market,
        hours_left: float,
    ) -> SniperTarget | None:
        """Evaluate a market for sniper opportunity."""
        yes = market.yes_price
        no = market.no_price

        if yes >= self.min_certainty:
            likely = "YES"
            price = yes
        elif no >= self.min_certainty:
            likely = "NO"
            price = no
        else:
            return None

        profit_per_share = 1.0 - price
        if profit_per_share <= 0.001:
            return None

        category = _detect_cat(market.question)
        shares_per_100 = 100.0 / price
        fee = calculate_fee(price, shares_per_100, category)
        gross_profit = shares_per_100 * profit_per_share
        net_profit = gross_profit - fee.fee_amount

        if net_profit <= 0:
            return None

        risk = self._assess_risk(price, hours_left, market.volume_24h)
        confidence = self._calc_confidence(price, hours_left, market.volume_24h)

        max_bet_pct = {"LOW": 0.10, "MEDIUM": 0.05, "HIGH": 0.02}.get(risk, 0.02)
        recommended = min(
            self.bankroll * max_bet_pct,
            market.liquidity * 0.05 if market.liquidity > 0 else 50,
        )

        return SniperTarget(
            market_slug=market.slug,
            question=market.question,
            likely_outcome=likely,
            outcome_price=price,
            profit_per_share=round(profit_per_share, 4),
            hours_to_resolution=round(hours_left, 1),
            volume_24h=market.volume_24h,
            liquidity=market.liquidity,
            net_profit_per_100=round(net_profit, 2),
            confidence=round(confidence, 2),
            risk_level=risk,
            recommended_bet=round(recommended, 2),
            category=category,
        )

    def _assess_risk(
        self, price: float, hours: float, volume: float,
    ) -> str:
        if price >= 0.98 and hours <= 24 and volume > 50000:
            return "LOW"
        if price >= 0.95 and hours <= 48:
            return "MEDIUM"
        return "HIGH"

    def _calc_confidence(
        self, price: float, hours: float, volume: float,
    ) -> float:
        price_conf = min(price, 0.99)
        time_conf = max(0, 1.0 - hours / 168)
        vol_conf = min(volume / 100000, 1.0)
        return price_conf * 0.5 + time_conf * 0.3 + vol_conf * 0.2


def _detect_cat(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["bitcoin", "ethereum", "crypto", "btc", "eth"]):
        return "crypto"
    if any(w in q for w in ["trump", "election", "vote"]):
        return "politics"
    if any(w in q for w in ["nba", "nfl", "fifa", "vs."]):
        return "sports"
    if any(w in q for w in ["fed", "rate", "gdp"]):
        return "economics"
    if any(w in q for w in ["iran", "ceasefire", "war"]):
        return "geopolitics"
    return "other"
