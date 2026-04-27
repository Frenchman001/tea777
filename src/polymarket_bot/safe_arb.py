"""Safe Arbitrage — guaranteed profit calculator with exact position sizing.

Unlike basic arb scanning, this module calculates the EXACT amounts to buy
on each side to lock in guaranteed profit AFTER all Polymarket fees.
Shows net profit in dollars, not just percentages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.models import Market
from polymarket_bot.profit_engine import calculate_fee

logger = logging.getLogger(__name__)


@dataclass
class SafeArbPosition:
    market_slug: str
    question: str
    yes_price: float
    no_price: float
    price_sum: float
    buy_yes_shares: float
    buy_no_shares: float
    total_cost: float
    guaranteed_payout: float
    fee_yes: float
    fee_no: float
    total_fees: float
    net_profit: float
    net_profit_pct: float
    roi_annualized: float
    category: str
    is_profitable: bool

    @property
    def description(self) -> str:
        status = "SAFE" if self.is_profitable else "UNPROFITABLE"
        return (
            f"[{status}] {self.question[:40]} | "
            f"Cost: ${self.total_cost:.2f} → Payout: ${self.guaranteed_payout:.2f} | "
            f"Net: ${self.net_profit:.2f} ({self.net_profit_pct:.2f}%)"
        )


class SafeArbEngine:
    """Calculates exact position sizes for guaranteed arbitrage profit."""

    def __init__(self, bankroll: float = 1000.0) -> None:
        self.bankroll = bankroll

    def scan(
        self,
        client: PolymarketClient,
        markets: list[Market],
    ) -> list[SafeArbPosition]:
        """Find guaranteed arb positions with exact sizing after fees."""
        positions: list[SafeArbPosition] = []

        for market in markets:
            if not market.active or market.closed:
                continue

            if market.price_sum >= 1.0:
                continue

            pos = self._calculate_position(client, market)
            if pos and pos.is_profitable:
                positions.append(pos)

        positions.sort(key=lambda p: p.net_profit, reverse=True)
        return positions

    def _calculate_position(
        self,
        client: PolymarketClient,
        market: Market,
    ) -> SafeArbPosition | None:
        """Calculate exact position sizing for guaranteed profit."""
        yes_price = market.yes_price
        no_price = market.no_price

        if yes_price <= 0.01 or no_price <= 0.01:
            return None
        if yes_price >= 0.99 or no_price >= 0.99:
            return None

        price_sum = yes_price + no_price
        if price_sum >= 1.0:
            return None

        try:
            book_yes = client.get_order_book(market.yes_token_id) if market.yes_token_id else None
            book_no = client.get_order_book(market.no_token_id) if market.no_token_id else None

            if book_yes and book_yes.best_ask > 0:
                yes_price = book_yes.best_ask
            if book_no and book_no.best_ask > 0:
                no_price = book_no.best_ask
        except Exception:
            pass

        price_sum = yes_price + no_price
        if price_sum >= 1.0:
            return None

        category = _detect_category(market.question)

        max_invest = min(self.bankroll * 0.10, 200.0)

        shares = max_invest / price_sum
        buy_yes_cost = shares * yes_price
        buy_no_cost = shares * no_price
        total_cost = buy_yes_cost + buy_no_cost

        fee_yes = calculate_fee(yes_price, shares, category)
        fee_no = calculate_fee(no_price, shares, category)
        total_fees = fee_yes.fee_amount + fee_no.fee_amount

        guaranteed_payout = shares * 1.0
        net_profit = guaranteed_payout - total_cost - total_fees

        is_profitable = net_profit > 0.01

        net_profit_pct = (net_profit / total_cost * 100) if total_cost > 0 else 0

        if is_profitable:
            optimal = self._optimize_shares(
                yes_price, no_price, category, max_invest,
            )
            if optimal:
                shares, buy_yes_cost, buy_no_cost, total_cost, total_fees, net_profit = optimal
                guaranteed_payout = shares
                net_profit_pct = (net_profit / total_cost * 100) if total_cost > 0 else 0

        roi_annualized = net_profit_pct * 365 / 7

        return SafeArbPosition(
            market_slug=market.slug,
            question=market.question,
            yes_price=yes_price,
            no_price=no_price,
            price_sum=price_sum,
            buy_yes_shares=shares if yes_price > 0 else 0,
            buy_no_shares=shares if no_price > 0 else 0,
            total_cost=round(total_cost, 2),
            guaranteed_payout=round(guaranteed_payout, 2),
            fee_yes=round(fee_yes.fee_amount, 4),
            fee_no=round(fee_no.fee_amount, 4),
            total_fees=round(total_fees, 4),
            net_profit=round(net_profit, 2),
            net_profit_pct=round(net_profit_pct, 2),
            roi_annualized=round(roi_annualized, 1),
            category=category,
            is_profitable=is_profitable,
        )

    def _optimize_shares(
        self,
        yes_price: float,
        no_price: float,
        category: str,
        max_invest: float,
    ) -> tuple[float, float, float, float, float, float] | None:
        """Binary search for optimal share count maximizing net profit."""
        best_profit = -1.0
        best_result = None

        low, high = 1.0, max_invest / (yes_price + no_price)
        for _ in range(30):
            mid = (low + high) / 2
            yes_cost = mid * yes_price
            no_cost = mid * no_price
            cost = yes_cost + no_cost

            if cost > max_invest:
                high = mid
                continue

            fy = calculate_fee(yes_price, mid, category)
            fn = calculate_fee(no_price, mid, category)
            fees = fy.fee_amount + fn.fee_amount

            profit = mid - cost - fees

            if profit > best_profit:
                best_profit = profit
                best_result = (mid, yes_cost, no_cost, cost, fees, profit)

            if profit > 0:
                low = mid
            else:
                high = mid

        return best_result


def _detect_category(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ["bitcoin", "ethereum", "crypto", "btc", "eth"]):
        return "crypto"
    if any(w in q for w in ["trump", "election", "president", "vote", "congress"]):
        return "politics"
    if any(w in q for w in ["nba", "nfl", "fifa", "match", "vs.", "win"]):
        return "sports"
    if any(w in q for w in ["fed", "rate", "gdp", "inflation", "treasury"]):
        return "economics"
    if any(w in q for w in ["iran", "russia", "ukraine", "ceasefire", "nato"]):
        return "geopolitics"
    return "other"
