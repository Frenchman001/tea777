"""Hedge Engine — automatic position hedging across correlated markets.

For any position you hold, finds correlated markets where you can place
an opposite bet to reduce or eliminate downside risk. If you're long YES
on "Bitcoin hits $100k", hedge with NO on "Bitcoin above $90k".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)


@dataclass
class HedgePair:
    primary_slug: str
    primary_question: str
    primary_side: str  # YES or NO
    primary_price: float
    hedge_slug: str
    hedge_question: str
    hedge_side: str
    hedge_price: float
    correlation: float  # 0-1, how strongly they move together
    hedge_ratio: float  # how much hedge per $1 of primary
    max_loss_pct: float  # worst-case loss after hedge
    expected_profit_pct: float
    hedge_type: str  # DIRECT, INVERSE, PARTIAL

    @property
    def description(self) -> str:
        return (
            f"[{self.hedge_type}] {self.primary_question[:30]} → {self.hedge_question[:30]} | "
            f"Max loss: {self.max_loss_pct:.1f}% | Expected: +{self.expected_profit_pct:.1f}%"
        )


class HedgeEngine:
    """Finds hedging opportunities across correlated markets."""

    def __init__(self, min_correlation: float = 0.5) -> None:
        self.min_correlation = min_correlation

    def find_hedges(
        self,
        target: Market,
        target_side: str,
        markets: list[Market],
        max_results: int = 5,
    ) -> list[HedgePair]:
        """Find hedge opportunities for a given position."""
        hedges: list[HedgePair] = []
        target_price = target.yes_price if target_side == "YES" else target.no_price

        if target_price <= 0.01 or target_price >= 0.99:
            return []

        for candidate in markets:
            if candidate.condition_id == target.condition_id:
                continue
            if not candidate.active or candidate.closed:
                continue

            pair = self._evaluate_hedge(target, target_side, target_price, candidate)
            if pair:
                hedges.append(pair)

        hedges.sort(key=lambda h: h.max_loss_pct)
        return hedges[:max_results]

    def find_all_hedges(
        self,
        markets: list[Market],
        max_pairs: int = 20,
    ) -> list[HedgePair]:
        """Find the best hedging pairs across all markets."""
        all_hedges: list[HedgePair] = []

        active = [m for m in markets if m.active and not m.closed]

        for i, market in enumerate(active):
            if market.yes_price < 0.15 or market.yes_price > 0.85:
                continue

            hedges = self.find_hedges(
                market, "YES", active[i + 1:], max_results=2,
            )
            all_hedges.extend(hedges)

        all_hedges.sort(key=lambda h: h.max_loss_pct)
        return all_hedges[:max_pairs]

    def _evaluate_hedge(
        self,
        target: Market,
        target_side: str,
        target_price: float,
        candidate: Market,
    ) -> HedgePair | None:
        """Evaluate if a candidate market can hedge the target position."""
        corr = self._estimate_correlation(target, candidate)
        if corr < self.min_correlation:
            return None

        if corr > 0.7:
            hedge_side = "NO" if target_side == "YES" else "YES"
            hedge_type = "DIRECT"
        else:
            hedge_side = target_side
            hedge_type = "PARTIAL"

        hedge_price = candidate.yes_price if hedge_side == "YES" else candidate.no_price
        if hedge_price <= 0.01 or hedge_price >= 0.99:
            return None

        hedge_ratio = target_price / max(hedge_price, 0.01)
        hedge_ratio = min(hedge_ratio, 3.0)

        scenario_both_win = (1.0 - target_price) + hedge_ratio * (1.0 - hedge_price)
        scenario_primary_lose = -target_price + hedge_ratio * (1.0 - hedge_price)
        scenario_hedge_lose = (1.0 - target_price) - hedge_ratio * hedge_price
        scenario_both_lose = -target_price - hedge_ratio * hedge_price

        total_invested = target_price + hedge_ratio * hedge_price

        if hedge_type == "DIRECT":
            max_loss = min(scenario_primary_lose, scenario_hedge_lose) / total_invested * 100
            expected = (scenario_both_win * corr + scenario_primary_lose * (1 - corr) * 0.5 +
                        scenario_hedge_lose * (1 - corr) * 0.5) / total_invested * 100
        else:
            max_loss = scenario_both_lose / total_invested * 100
            expected = (scenario_both_win * corr * 0.5 + scenario_primary_lose * 0.25 +
                        scenario_hedge_lose * 0.25) / total_invested * 100

        if max_loss < -50:
            return None

        return HedgePair(
            primary_slug=target.slug,
            primary_question=target.question,
            primary_side=target_side,
            primary_price=target_price,
            hedge_slug=candidate.slug,
            hedge_question=candidate.question,
            hedge_side=hedge_side,
            hedge_price=hedge_price,
            correlation=round(corr, 2),
            hedge_ratio=round(hedge_ratio, 2),
            max_loss_pct=round(max_loss, 1),
            expected_profit_pct=round(expected, 1),
            hedge_type=hedge_type,
        )

    def _estimate_correlation(self, a: Market, b: Market) -> float:
        """Estimate correlation between two markets using text + context."""
        q1 = a.question.lower()
        q2 = b.question.lower()

        text_sim = SequenceMatcher(None, q1, q2).ratio()

        topic_boost = 0.0
        topics = [
            ["bitcoin", "btc", "crypto", "ethereum"],
            ["trump", "election", "president", "republican", "democrat"],
            ["fed", "rate", "interest", "monetary"],
            ["iran", "ceasefire", "peace", "war", "conflict"],
            ["nba", "nfl", "soccer", "football", "basketball"],
        ]
        for topic in topics:
            a_match = any(w in q1 for w in topic)
            b_match = any(w in q2 for w in topic)
            if a_match and b_match:
                topic_boost = 0.2
                break

        nums_a = _extract_nums(q1)
        nums_b = _extract_nums(q2)
        if nums_a and nums_b and text_sim > 0.5:
            if nums_a == nums_b:
                topic_boost += 0.1
            else:
                topic_boost -= 0.1

        if a.event_slug and b.event_slug and a.event_slug == b.event_slug:
            return min(0.9, text_sim + 0.3)

        corr = text_sim * 0.7 + topic_boost
        return max(0, min(corr, 1.0))


def _extract_nums(text: str) -> list[float]:
    matches = re.findall(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    return sorted(float(m) for m in matches if float(m) > 1)
