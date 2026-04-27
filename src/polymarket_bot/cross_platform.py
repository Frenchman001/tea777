"""Cross-platform arbitrage — compares Polymarket with Kalshi and others.

Finds price discrepancies between prediction market platforms
for the same or similar events.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import httpx

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)


@dataclass
class ExternalMarket:
    platform: str
    title: str
    yes_price: float
    no_price: float
    url: str = ""
    volume: float = 0.0


@dataclass
class CrossPlatformArb:
    polymarket: Market
    external: ExternalMarket
    poly_yes: float
    ext_yes: float
    price_diff: float
    arb_type: str
    recommended_action: str
    estimated_profit_pct: float

    @property
    def description(self) -> str:
        return (
            f"[CROSS-ARB] {self.polymarket.question[:40]} | "
            f"Poly: {self.poly_yes:.0%} vs {self.external.platform}: {self.ext_yes:.0%} | "
            f"Diff: {self.price_diff:.1%}"
        )


class KalshiScanner:
    """Scans Kalshi markets for cross-platform comparison.

    Uses Kalshi's public API to fetch market data.
    Note: Kalshi API may require authentication for some endpoints.
    """

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=15.0)
        self._markets: list[ExternalMarket] = []

    def close(self) -> None:
        self._http.close()

    def fetch_markets(self, limit: int = 100) -> list[ExternalMarket]:
        """Fetch active Kalshi markets."""
        try:
            resp = self._http.get(
                f"{self.BASE_URL}/markets",
                params={"limit": limit, "status": "open"},
            )
            resp.raise_for_status()
            data = resp.json()

            markets = []
            for m in data.get("markets", []):
                yes_price = m.get("yes_ask", 0) / 100.0 if m.get("yes_ask") else 0
                no_price = m.get("no_ask", 0) / 100.0 if m.get("no_ask") else 0

                markets.append(ExternalMarket(
                    platform="Kalshi",
                    title=m.get("title", ""),
                    yes_price=yes_price,
                    no_price=no_price,
                    url=f"https://kalshi.com/markets/{m.get('ticker', '')}",
                    volume=m.get("volume", 0),
                ))

            self._markets = markets
            return markets
        except Exception as e:
            logger.debug("Kalshi fetch failed: %s", e)
            return []


class CrossPlatformScanner:
    """Finds arbitrage opportunities across prediction market platforms."""

    def __init__(self) -> None:
        self.kalshi = KalshiScanner()

    def close(self) -> None:
        self.kalshi.close()

    def find_cross_arb(
        self,
        polymarket_markets: list[Market],
        min_diff: float = 0.05,
    ) -> list[CrossPlatformArb]:
        """Compare Polymarket with external platforms for arbitrage."""
        arbs: list[CrossPlatformArb] = []

        ext_markets = self.kalshi.fetch_markets()
        if not ext_markets:
            logger.info("No external markets fetched, trying keyword matching only")
            return arbs

        for poly in polymarket_markets:
            for ext in ext_markets:
                similarity = _question_similarity(poly.question, ext.title)
                if similarity < 0.5:
                    continue

                poly_yes = poly.yes_price
                ext_yes = ext.yes_price
                if poly_yes <= 0 or ext_yes <= 0:
                    continue

                diff = abs(poly_yes - ext_yes)
                if diff < min_diff:
                    continue

                if poly_yes < ext_yes:
                    action = (
                        f"Buy YES on Polymarket @ {poly_yes:.0%}, "
                        f"Sell on {ext.platform} @ {ext_yes:.0%}"
                    )
                    arb_type = "BUY_POLY"
                else:
                    action = (
                        f"Buy YES on {ext.platform} @ {ext_yes:.0%}, "
                        f"Sell on Polymarket @ {poly_yes:.0%}"
                    )
                    arb_type = "BUY_EXT"

                profit_pct = diff * 100

                arbs.append(CrossPlatformArb(
                    polymarket=poly,
                    external=ext,
                    poly_yes=poly_yes,
                    ext_yes=ext_yes,
                    price_diff=diff,
                    arb_type=arb_type,
                    recommended_action=action,
                    estimated_profit_pct=round(profit_pct, 2),
                ))

        arbs.sort(key=lambda a: a.price_diff, reverse=True)
        return arbs

    def find_internal_cross_arb(
        self,
        markets: list[Market],
        min_diff: float = 0.05,
    ) -> list[CrossPlatformArb]:
        """Find arbitrage between similar Polymarket markets (same event, different wording)."""
        arbs: list[CrossPlatformArb] = []

        for i in range(len(markets)):
            for j in range(i + 1, min(i + 50, len(markets))):
                a, b = markets[i], markets[j]
                sim = _question_similarity(a.question, b.question)
                if sim < 0.6:
                    continue

                diff = abs(a.yes_price - b.yes_price)
                if diff < min_diff:
                    continue

                cheap = a if a.yes_price < b.yes_price else b
                expensive = b if a.yes_price < b.yes_price else a

                arbs.append(CrossPlatformArb(
                    polymarket=cheap,
                    external=ExternalMarket(
                        platform="Polymarket",
                        title=expensive.question,
                        yes_price=expensive.yes_price,
                        no_price=expensive.no_price,
                    ),
                    poly_yes=cheap.yes_price,
                    ext_yes=expensive.yes_price,
                    price_diff=diff,
                    arb_type="INTERNAL",
                    recommended_action=(
                        f"Buy YES on '{cheap.question[:30]}...' @ {cheap.yes_price:.0%}, "
                        f"opposite on '{expensive.question[:30]}...' @ {expensive.yes_price:.0%}"
                    ),
                    estimated_profit_pct=round(diff * 100, 2),
                ))

        arbs.sort(key=lambda a: a.price_diff, reverse=True)
        return arbs[:20]


def _question_similarity(q1: str, q2: str) -> float:
    """Calculate string similarity between two market questions.

    Returns 0.0 if the questions differ only in embedded numbers
    (e.g. different strike prices like $78k vs $72k).
    """
    q1_clean = _normalize(q1)
    q2_clean = _normalize(q2)

    base_sim = SequenceMatcher(None, q1_clean, q2_clean).ratio()
    if base_sim < 0.5:
        return base_sim

    nums1 = _extract_numbers(q1)
    nums2 = _extract_numbers(q2)
    if nums1 and nums2 and nums1 != nums2:
        text1_no_nums = re.sub(r"[\d,.]+[kKmMbB]?", "", q1_clean).strip()
        text2_no_nums = re.sub(r"[\d,.]+[kKmMbB]?", "", q2_clean).strip()
        text_only_sim = SequenceMatcher(None, text1_no_nums, text2_no_nums).ratio()
        if text_only_sim > 0.85:
            return 0.0

    return base_sim


def _extract_numbers(text: str) -> list[float]:
    """Extract all meaningful numbers from a market question."""
    text_clean = text.lower().replace(",", "")
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*([kKmMbB])?", text_clean)
    nums: list[float] = []
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    for val, suffix in matches:
        n = float(val)
        if suffix:
            n *= multipliers.get(suffix.lower(), 1)
        if n > 1:
            nums.append(n)
    return sorted(nums)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
