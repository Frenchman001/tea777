"""Market making strategy — earns spread by quoting both sides.

Places bid and ask orders on both YES and NO sides, earning
the bid-ask spread when both sides fill. Requires active position
management and inventory hedging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.models import Market, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    side: str
    price: float
    size: float
    token_id: str


@dataclass
class MMPosition:
    market_slug: str
    yes_inventory: float = 0.0
    no_inventory: float = 0.0
    realized_pnl: float = 0.0
    num_fills: int = 0

    @property
    def net_exposure(self) -> float:
        return self.yes_inventory - self.no_inventory

    @property
    def is_balanced(self) -> bool:
        return abs(self.net_exposure) < 10


@dataclass
class MMStrategy:
    spread_pct: float = 0.03
    order_size: float = 50.0
    max_inventory: float = 500.0
    min_spread: float = 0.01
    rebalance_threshold: float = 0.6
    max_positions: int = 5


@dataclass
class MMQuoteSet:
    market_slug: str
    bid_yes: Quote | None = None
    ask_yes: Quote | None = None
    bid_no: Quote | None = None
    ask_no: Quote | None = None
    spread: float = 0.0

    @property
    def num_quotes(self) -> int:
        return sum(1 for q in [self.bid_yes, self.ask_yes, self.bid_no, self.ask_no] if q)


class MarketMaker:
    """Market making engine for earning bid-ask spread."""

    def __init__(self, strategy: MMStrategy | None = None) -> None:
        self.strategy = strategy or MMStrategy()
        self.positions: dict[str, MMPosition] = {}
        self._active = False

    def generate_quotes(
        self, market: Market, orderbook: OrderBook | None = None,
    ) -> MMQuoteSet:
        """Generate bid/ask quotes for a market."""
        yes_price = market.yes_price
        no_price = market.no_price

        if yes_price <= 0.05 or yes_price >= 0.95:
            return MMQuoteSet(market_slug=market.slug)

        pos = self.positions.get(market.slug, MMPosition(market_slug=market.slug))

        half_spread = self.strategy.spread_pct / 2

        if orderbook and orderbook.spread > 0:
            effective_spread = max(orderbook.spread * 0.8, self.strategy.min_spread)
            half_spread = effective_spread / 2

        inventory_skew = 0.0
        if abs(pos.net_exposure) > self.strategy.order_size:
            skew_factor = pos.net_exposure / self.strategy.max_inventory
            inventory_skew = skew_factor * half_spread

        bid_yes_price = round(yes_price - half_spread - inventory_skew, 4)
        ask_yes_price = round(yes_price + half_spread - inventory_skew, 4)
        bid_no_price = round(no_price - half_spread + inventory_skew, 4)
        ask_no_price = round(no_price + half_spread + inventory_skew, 4)

        bid_yes_price = max(0.01, min(bid_yes_price, 0.99))
        ask_yes_price = max(0.01, min(ask_yes_price, 0.99))
        bid_no_price = max(0.01, min(bid_no_price, 0.99))
        ask_no_price = max(0.01, min(ask_no_price, 0.99))

        yes_id = market.yes_token_id or ""
        no_id = market.no_token_id or ""

        quotes = MMQuoteSet(
            market_slug=market.slug,
            spread=ask_yes_price - bid_yes_price,
        )

        if abs(pos.yes_inventory) < self.strategy.max_inventory:
            quotes.bid_yes = Quote(
                side="BUY", price=bid_yes_price,
                size=self.strategy.order_size, token_id=yes_id,
            )
            quotes.ask_yes = Quote(
                side="SELL", price=ask_yes_price,
                size=self.strategy.order_size, token_id=yes_id,
            )

        if abs(pos.no_inventory) < self.strategy.max_inventory:
            quotes.bid_no = Quote(
                side="BUY", price=bid_no_price,
                size=self.strategy.order_size, token_id=no_id,
            )
            quotes.ask_no = Quote(
                side="SELL", price=ask_no_price,
                size=self.strategy.order_size, token_id=no_id,
            )

        return quotes

    def select_markets(
        self, markets: list[Market], min_volume: float = 10000,
    ) -> list[Market]:
        """Select best markets for market making based on volume and spread."""
        candidates: list[tuple[float, Market]] = []

        for m in markets:
            if m.volume_24h < min_volume:
                continue
            if m.yes_price <= 0.1 or m.yes_price >= 0.9:
                continue
            if m.liquidity < 5000:
                continue

            score = (
                m.volume_24h / 100000
                + m.liquidity / 50000
                + (1.0 - abs(m.yes_price - 0.5) * 2) * 0.5
            )
            candidates.append((score, m))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in candidates[:self.strategy.max_positions]]

    def simulate_fill(
        self, market_slug: str, side: str, price: float, size: float,
    ) -> None:
        """Record a simulated fill for PnL tracking."""
        if market_slug not in self.positions:
            self.positions[market_slug] = MMPosition(market_slug=market_slug)

        pos = self.positions[market_slug]
        pos.num_fills += 1

        if "YES" in side.upper():
            if "BUY" in side.upper():
                pos.yes_inventory += size
                pos.realized_pnl -= price * size
            else:
                pos.yes_inventory -= size
                pos.realized_pnl += price * size
        else:
            if "BUY" in side.upper():
                pos.no_inventory += size
                pos.realized_pnl -= price * size
            else:
                pos.no_inventory -= size
                pos.realized_pnl += price * size

    def get_summary(self) -> dict:
        """Return market making summary."""
        total_pnl = sum(p.realized_pnl for p in self.positions.values())
        total_fills = sum(p.num_fills for p in self.positions.values())
        balanced = sum(1 for p in self.positions.values() if p.is_balanced)

        return {
            "active_markets": len(self.positions),
            "total_fills": total_fills,
            "total_pnl": round(total_pnl, 2),
            "balanced_positions": balanced,
            "positions": {
                slug: {
                    "yes_inv": p.yes_inventory,
                    "no_inv": p.no_inventory,
                    "pnl": round(p.realized_pnl, 2),
                    "fills": p.num_fills,
                }
                for slug, p in self.positions.items()
            },
        }
