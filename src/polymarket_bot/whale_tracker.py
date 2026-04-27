"""Whale Tracker — detects smart money positioning via CLOB orderbook analysis.

Most bots only look at prices. This module analyzes the ORDER SIZE DISTRIBUTION
to find whale activity: large limit orders that signal informed trader conviction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.models import Market, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class WhaleSignal:
    market_slug: str
    question: str
    signal: str  # WHALE_BID, WHALE_ASK, BID_WALL, ASK_WALL
    side: str  # YES or NO
    whale_size_usd: float
    total_book_usd: float
    whale_pct: float
    imbalance_ratio: float
    current_price: float
    recommended_action: str
    confidence: float

    @property
    def description(self) -> str:
        return (
            f"[{self.signal}] {self.question[:45]} | "
            f"Whale: ${self.whale_size_usd:.0f} ({self.whale_pct:.0%} of book) | "
            f"Imbalance: {self.imbalance_ratio:.1f}x | {self.recommended_action}"
        )


@dataclass
class OrderDistribution:
    total_usd: float
    large_order_usd: float
    large_order_count: int
    avg_order_size: float
    max_order_size: float
    whale_pct: float


class WhaleTracker:
    """Analyzes CLOB orderbook to detect smart money positioning."""

    def __init__(
        self,
        whale_threshold_usd: float = 500.0,
        imbalance_threshold: float = 2.0,
    ) -> None:
        self.whale_threshold = whale_threshold_usd
        self.imbalance_threshold = imbalance_threshold

    def analyze_market(
        self,
        client: PolymarketClient,
        market: Market,
    ) -> list[WhaleSignal]:
        """Analyze a market's orderbook for whale activity."""
        token_id = market.yes_token_id
        if not token_id:
            return []

        try:
            book = client.get_order_book(token_id)
        except Exception:
            logger.debug("Failed to get orderbook for %s", market.slug)
            return []

        return self._analyze_book(book, market)

    def _analyze_book(
        self, book: OrderBook, market: Market,
    ) -> list[WhaleSignal]:
        """Detect whale patterns in the orderbook."""
        signals: list[WhaleSignal] = []

        bid_dist = self._distribution(book.bids)
        ask_dist = self._distribution(book.asks)

        if bid_dist.total_usd == 0 and ask_dist.total_usd == 0:
            return []

        bid_total = max(bid_dist.total_usd, 0.01)
        ask_total = max(ask_dist.total_usd, 0.01)
        imbalance = bid_total / ask_total

        if bid_dist.whale_pct > 0.3 and imbalance > self.imbalance_threshold:
            signals.append(WhaleSignal(
                market_slug=market.slug,
                question=market.question,
                signal="WHALE_BID",
                side="YES",
                whale_size_usd=bid_dist.large_order_usd,
                total_book_usd=bid_dist.total_usd,
                whale_pct=bid_dist.whale_pct,
                imbalance_ratio=imbalance,
                current_price=market.yes_price,
                recommended_action=f"BUY YES @ {market.yes_price:.3f} (whale support)",
                confidence=min(0.5 + bid_dist.whale_pct * 0.3 + (imbalance - 1) * 0.1, 0.95),
            ))

        inv_imbalance = ask_total / bid_total
        if ask_dist.whale_pct > 0.3 and inv_imbalance > self.imbalance_threshold:
            signals.append(WhaleSignal(
                market_slug=market.slug,
                question=market.question,
                signal="WHALE_ASK",
                side="NO",
                whale_size_usd=ask_dist.large_order_usd,
                total_book_usd=ask_dist.total_usd,
                whale_pct=ask_dist.whale_pct,
                imbalance_ratio=inv_imbalance,
                current_price=market.yes_price,
                recommended_action=f"BUY NO @ {market.no_price:.3f} (whale selling YES)",
                confidence=min(0.5 + ask_dist.whale_pct * 0.3 + (inv_imbalance - 1) * 0.1, 0.95),
            ))

        if bid_dist.max_order_size > self.whale_threshold * 3:
            signals.append(WhaleSignal(
                market_slug=market.slug,
                question=market.question,
                signal="BID_WALL",
                side="YES",
                whale_size_usd=bid_dist.max_order_size,
                total_book_usd=bid_dist.total_usd,
                whale_pct=bid_dist.max_order_size / bid_total,
                imbalance_ratio=imbalance,
                current_price=market.yes_price,
                recommended_action=f"BUY YES — ${bid_dist.max_order_size:.0f} bid wall support",
                confidence=min(0.6 + bid_dist.max_order_size / 10000, 0.9),
            ))

        if ask_dist.max_order_size > self.whale_threshold * 3:
            signals.append(WhaleSignal(
                market_slug=market.slug,
                question=market.question,
                signal="ASK_WALL",
                side="NO",
                whale_size_usd=ask_dist.max_order_size,
                total_book_usd=ask_dist.total_usd,
                whale_pct=ask_dist.max_order_size / ask_total,
                imbalance_ratio=inv_imbalance,
                current_price=market.yes_price,
                recommended_action=f"SELL YES — ${ask_dist.max_order_size:.0f} ask wall resistance",
                confidence=min(0.6 + ask_dist.max_order_size / 10000, 0.9),
            ))

        return signals

    def _distribution(self, levels: list) -> OrderDistribution:
        """Analyze order size distribution."""
        if not levels:
            return OrderDistribution(0, 0, 0, 0, 0, 0)

        sizes = [lv.price * lv.size for lv in levels]
        total = sum(sizes)
        large = [s for s in sizes if s >= self.whale_threshold]

        return OrderDistribution(
            total_usd=total,
            large_order_usd=sum(large),
            large_order_count=len(large),
            avg_order_size=total / len(sizes) if sizes else 0,
            max_order_size=max(sizes) if sizes else 0,
            whale_pct=sum(large) / total if total > 0 else 0,
        )

    def scan_markets(
        self,
        client: PolymarketClient,
        markets: list[Market],
        max_scan: int = 30,
    ) -> list[WhaleSignal]:
        """Scan multiple markets for whale activity."""
        all_signals: list[WhaleSignal] = []
        scanned = 0

        sorted_markets = sorted(markets, key=lambda m: m.volume_24h, reverse=True)

        for market in sorted_markets[:max_scan]:
            if not market.yes_token_id:
                continue
            signals = self.analyze_market(client, market)
            all_signals.extend(signals)
            scanned += 1

        all_signals.sort(key=lambda s: s.whale_size_usd, reverse=True)
        logger.info("Scanned %d markets, found %d whale signals", scanned, len(all_signals))
        return all_signals
