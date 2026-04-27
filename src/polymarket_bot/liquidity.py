"""Liquidity verification — checks orderbook depth before recommending bets."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.models import Market, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class LiquidityCheck:
    market_slug: str
    side: str
    recommended_bet_usd: float
    available_depth_usd: float
    fillable: bool
    avg_fill_price: float
    slippage_pct: float
    levels_consumed: int

    @property
    def is_safe(self) -> bool:
        return self.fillable and self.slippage_pct < 3.0


def check_liquidity(
    client: PolymarketClient,
    market: Market,
    side: str,
    bet_usd: float,
) -> LiquidityCheck:
    """Check if an orderbook can fill the recommended bet without excessive slippage."""
    token_id = market.yes_token_id if side.upper() == "YES" else market.no_token_id
    if not token_id:
        return LiquidityCheck(
            market_slug=market.slug, side=side,
            recommended_bet_usd=bet_usd, available_depth_usd=0.0,
            fillable=False, avg_fill_price=0.0, slippage_pct=100.0,
            levels_consumed=0,
        )

    try:
        book = client.get_order_book(token_id)
    except Exception:
        logger.debug("Failed to fetch orderbook for %s", market.slug)
        return LiquidityCheck(
            market_slug=market.slug, side=side,
            recommended_bet_usd=bet_usd, available_depth_usd=0.0,
            fillable=False, avg_fill_price=0.0, slippage_pct=100.0,
            levels_consumed=0,
        )

    return _simulate_fill(book, bet_usd, market.slug, side)


def _simulate_fill(
    book: OrderBook,
    bet_usd: float,
    slug: str,
    side: str,
) -> LiquidityCheck:
    """Walk the ask side of the orderbook and simulate filling the order."""
    asks = sorted(book.asks, key=lambda a: a.price)
    if not asks:
        return LiquidityCheck(
            market_slug=slug, side=side,
            recommended_bet_usd=bet_usd, available_depth_usd=0.0,
            fillable=False, avg_fill_price=0.0, slippage_pct=100.0,
            levels_consumed=0,
        )

    remaining = bet_usd
    total_shares = 0.0
    total_cost = 0.0
    levels = 0

    for level in asks:
        level_cost = level.price * level.size
        if level_cost >= remaining:
            shares = remaining / level.price
            total_shares += shares
            total_cost += remaining
            remaining = 0.0
            levels += 1
            break
        total_shares += level.size
        total_cost += level_cost
        remaining -= level_cost
        levels += 1

    fillable = remaining <= 0
    avg_price = total_cost / total_shares if total_shares > 0 else 0.0
    best_price = asks[0].price if asks else 0.0
    slippage = ((avg_price - best_price) / best_price * 100) if best_price > 0 else 0.0

    return LiquidityCheck(
        market_slug=slug, side=side,
        recommended_bet_usd=bet_usd,
        available_depth_usd=round(total_cost, 2),
        fillable=fillable,
        avg_fill_price=round(avg_price, 4),
        slippage_pct=round(max(slippage, 0), 2),
        levels_consumed=levels,
    )


def filter_by_liquidity(
    client: PolymarketClient,
    markets: list[Market],
    min_depth_usd: float = 50.0,
) -> list[Market]:
    """Return only markets with sufficient ask-side liquidity."""
    liquid: list[Market] = []
    for m in markets:
        token_id = m.yes_token_id
        if not token_id:
            continue
        try:
            book = client.get_order_book(token_id)
            depth = sum(a.price * a.size for a in book.asks)
            if depth >= min_depth_usd:
                liquid.append(m)
        except Exception:
            continue
    return liquid
