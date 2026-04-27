"""Volume Anomaly Detector — finds unusual trading patterns that signal insider knowledge.

When volume suddenly spikes relative to historical average, it often means:
- Informed traders positioning before news
- Insider activity
- Breaking event about to move the market

This module detects volume spikes and correlates with price movement direction
to generate actionable signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)


@dataclass
class VolumeAnomaly:
    market_slug: str
    question: str
    volume_24h: float
    liquidity: float
    volume_liquidity_ratio: float
    price_direction: str  # UP, DOWN, NEUTRAL
    yes_price: float
    anomaly_score: float  # 0-10, higher = more unusual
    anomaly_type: str  # VOLUME_SPIKE, HIGH_TURNOVER, ILLIQUID_SURGE
    recommended_action: str
    confidence: float

    @property
    def description(self) -> str:
        return (
            f"[{self.anomaly_type}] {self.question[:45]} | "
            f"Vol: ${self.volume_24h:,.0f} | V/L: {self.volume_liquidity_ratio:.1f}x | "
            f"Score: {self.anomaly_score:.1f}/10 | {self.recommended_action}"
        )


class VolumeAnomalyDetector:
    """Detects unusual volume patterns across Polymarket markets."""

    def __init__(
        self,
        min_volume: float = 5000.0,
        spike_threshold: float = 3.0,
        turnover_threshold: float = 2.0,
    ) -> None:
        self.min_volume = min_volume
        self.spike_threshold = spike_threshold
        self.turnover_threshold = turnover_threshold

    def scan(self, markets: list[Market]) -> list[VolumeAnomaly]:
        """Scan markets for volume anomalies."""
        if len(markets) < 5:
            return []

        volumes = [m.volume_24h for m in markets if m.volume_24h > 0]
        if not volumes:
            return []

        median_vol = sorted(volumes)[len(volumes) // 2]
        avg_vol = sum(volumes) / len(volumes)

        anomalies: list[VolumeAnomaly] = []

        for market in markets:
            if not market.active or market.closed:
                continue

            results = self._check_anomalies(market, median_vol, avg_vol)
            anomalies.extend(results)

        anomalies.sort(key=lambda a: a.anomaly_score, reverse=True)
        return anomalies

    def _check_anomalies(
        self,
        market: Market,
        median_vol: float,
        avg_vol: float,
    ) -> list[VolumeAnomaly]:
        """Check a single market for various anomaly types."""
        anomalies: list[VolumeAnomaly] = []

        vol = market.volume_24h
        liq = max(market.liquidity, 1.0)
        vl_ratio = vol / liq

        price_dir = self._infer_direction(market)

        if vol > 0 and median_vol > 0:
            spike = vol / median_vol
            if spike >= self.spike_threshold and vol >= self.min_volume:
                score = min(spike, 10.0)
                action = self._recommend(price_dir, market.yes_price, "volume leaders")

                anomalies.append(VolumeAnomaly(
                    market_slug=market.slug,
                    question=market.question,
                    volume_24h=vol,
                    liquidity=liq,
                    volume_liquidity_ratio=round(vl_ratio, 2),
                    price_direction=price_dir,
                    yes_price=market.yes_price,
                    anomaly_score=round(score, 1),
                    anomaly_type="VOLUME_SPIKE",
                    recommended_action=action,
                    confidence=min(0.4 + score * 0.05, 0.85),
                ))

        if vl_ratio >= self.turnover_threshold and vol >= self.min_volume:
            score = min(vl_ratio * 2, 10.0)
            action = self._recommend(price_dir, market.yes_price, "high turnover")

            anomalies.append(VolumeAnomaly(
                market_slug=market.slug,
                question=market.question,
                volume_24h=vol,
                liquidity=liq,
                volume_liquidity_ratio=round(vl_ratio, 2),
                price_direction=price_dir,
                yes_price=market.yes_price,
                anomaly_score=round(score, 1),
                anomaly_type="HIGH_TURNOVER",
                recommended_action=action,
                confidence=min(0.35 + vl_ratio * 0.08, 0.8),
            ))

        if liq > 0 and liq < 10000 and vol > liq * 5:
            score = min(vol / liq, 10.0)
            anomalies.append(VolumeAnomaly(
                market_slug=market.slug,
                question=market.question,
                volume_24h=vol,
                liquidity=liq,
                volume_liquidity_ratio=round(vl_ratio, 2),
                price_direction=price_dir,
                yes_price=market.yes_price,
                anomaly_score=round(score, 1),
                anomaly_type="ILLIQUID_SURGE",
                recommended_action="CAUTION — low liquidity, high slippage risk",
                confidence=0.3,
            ))

        return anomalies

    def _infer_direction(self, market: Market) -> str:
        """Infer price direction from current position."""
        yes = market.yes_price
        if yes > 0.7:
            return "UP"
        if yes < 0.3:
            return "DOWN"
        return "NEUTRAL"

    def _recommend(self, direction: str, price: float, context: str) -> str:
        if direction == "UP" and price < 0.85:
            return f"BUY YES — {context}, price trending up"
        if direction == "DOWN" and price > 0.15:
            return f"BUY NO — {context}, price trending down"
        return f"WATCH — {context}, unclear direction"
