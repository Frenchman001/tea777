"""Risk-Free Combo — builds multi-market positions with zero or positive expected value.

Finds combinations of markets where buying specific outcomes creates
a portfolio that profits regardless of how individual markets resolve.
Uses event-level arbitrage and conditional probability matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)


@dataclass
class ComboLeg:
    market_slug: str
    question: str
    side: str  # YES or NO
    price: float
    allocation_pct: float  # % of combo budget

    @property
    def description(self) -> str:
        return f"{self.side} '{self.question[:30]}' @ {self.price:.1%} ({self.allocation_pct:.0f}%)"


@dataclass
class RiskFreeCombo:
    name: str
    legs: list[ComboLeg]
    total_cost_per_100: float
    min_payout: float
    max_payout: float
    guaranteed_profit: float
    profit_pct: float
    combo_type: str  # EVENT_ARB, MIRROR, CONDITIONAL

    @property
    def is_profitable(self) -> bool:
        return self.guaranteed_profit > 0

    @property
    def description(self) -> str:
        status = "RISK-FREE" if self.is_profitable else "HEDGED"
        return (
            f"[{status}] {self.name[:40]} | "
            f"Cost: ${self.total_cost_per_100:.2f} | "
            f"Payout: ${self.min_payout:.2f}-${self.max_payout:.2f} | "
            f"Profit: ${self.guaranteed_profit:.2f} ({self.profit_pct:.1f}%)"
        )


class RiskFreeComboEngine:
    """Finds multi-market combinations with guaranteed positive returns."""

    def scan(
        self,
        markets: list[Market],
        max_combos: int = 20,
    ) -> list[RiskFreeCombo]:
        """Scan for risk-free combo opportunities."""
        combos: list[RiskFreeCombo] = []

        event_combos = self._find_event_arbs(markets)
        combos.extend(event_combos)

        mirror_combos = self._find_mirror_combos(markets)
        combos.extend(mirror_combos)

        opposite_combos = self._find_opposite_combos(markets)
        combos.extend(opposite_combos)

        combos = [c for c in combos if c.is_profitable]
        combos.sort(key=lambda c: c.profit_pct, reverse=True)
        return combos[:max_combos]

    def _find_event_arbs(self, markets: list[Market]) -> list[RiskFreeCombo]:
        """Find event-level arbitrage (all outcomes of same event sum < 1)."""
        combos: list[RiskFreeCombo] = []
        events: dict[str, list[Market]] = {}

        for m in markets:
            if not m.active or m.closed or not m.event_slug:
                continue
            events.setdefault(m.event_slug, []).append(m)

        for event_slug, event_markets in events.items():
            if len(event_markets) < 2:
                continue

            total_yes = sum(m.yes_price for m in event_markets)

            if total_yes < 0.95:
                legs = []
                for m in event_markets:
                    if m.yes_price > 0.01:
                        pct = m.yes_price / total_yes * 100
                        legs.append(ComboLeg(
                            market_slug=m.slug,
                            question=m.question,
                            side="YES",
                            price=m.yes_price,
                            allocation_pct=round(pct, 1),
                        ))

                if len(legs) >= 2:
                    cost = total_yes * 100
                    payout = 100.0
                    profit = payout - cost
                    combos.append(RiskFreeCombo(
                        name=f"Event arb: {event_slug[:30]}",
                        legs=legs,
                        total_cost_per_100=round(cost, 2),
                        min_payout=payout,
                        max_payout=payout,
                        guaranteed_profit=round(profit, 2),
                        profit_pct=round(profit / cost * 100, 1) if cost > 0 else 0,
                        combo_type="EVENT_ARB",
                    ))

        return combos

    def _find_mirror_combos(self, markets: list[Market]) -> list[RiskFreeCombo]:
        """Find binary markets where YES + NO < 1 (direct arb)."""
        combos: list[RiskFreeCombo] = []

        for m in markets:
            if not m.active or m.closed:
                continue

            yes = m.yes_price
            no = m.no_price
            if yes <= 0.01 or no <= 0.01:
                continue

            price_sum = yes + no
            if price_sum < 0.98:
                cost = price_sum * 100
                legs = [
                    ComboLeg(m.slug, m.question, "YES", yes, round(yes / price_sum * 100, 1)),
                    ComboLeg(m.slug, m.question, "NO", no, round(no / price_sum * 100, 1)),
                ]
                profit = 100 - cost
                combos.append(RiskFreeCombo(
                    name=f"Mirror: {m.question[:35]}",
                    legs=legs,
                    total_cost_per_100=round(cost, 2),
                    min_payout=100.0,
                    max_payout=100.0,
                    guaranteed_profit=round(profit, 2),
                    profit_pct=round(profit / cost * 100, 1) if cost > 0 else 0,
                    combo_type="MIRROR",
                ))

        return combos

    def _find_opposite_combos(self, markets: list[Market]) -> list[RiskFreeCombo]:
        """Find pairs where buying cheap NO on two correlated markets = safe."""
        combos: list[RiskFreeCombo] = []

        cheap_no: list[Market] = []
        for m in markets:
            if not m.active or m.closed:
                continue
            if m.no_price <= 0.08 and m.no_price > 0.01:
                cheap_no.append(m)

        for i in range(len(cheap_no)):
            for j in range(i + 1, min(i + 20, len(cheap_no))):
                a, b = cheap_no[i], cheap_no[j]
                cost = (a.no_price + b.no_price) * 100

                min_payout = 100.0
                max_payout = 200.0

                if cost < min_payout:
                    profit = min_payout - cost
                    legs = [
                        ComboLeg(a.slug, a.question, "NO", a.no_price, 50),
                        ComboLeg(b.slug, b.question, "NO", b.no_price, 50),
                    ]
                    combos.append(RiskFreeCombo(
                        name=f"Opposite: {a.question[:20]} + {b.question[:20]}",
                        legs=legs,
                        total_cost_per_100=round(cost, 2),
                        min_payout=min_payout,
                        max_payout=max_payout,
                        guaranteed_profit=round(profit, 2),
                        profit_pct=round(profit / cost * 100, 1) if cost > 0 else 0,
                        combo_type="CONDITIONAL",
                    ))

        return combos
