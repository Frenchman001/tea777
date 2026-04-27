"""Trading signal generator for Polymarket."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.config import Config
from polymarket_bot.models import Market, SignalStrength, SignalType, TradingSignal

logger = logging.getLogger(__name__)


class SignalAnalyzer:
    """Analyzes markets and generates trading signals."""

    def __init__(self, client: PolymarketClient, config: Config | None = None) -> None:
        self.client = client
        self.config = config or Config()

    def analyze_markets(self, markets: list[Market] | None = None) -> list[TradingSignal]:
        if markets is None:
            markets = self.client.get_all_active_markets()

        signals: list[TradingSignal] = []
        for market in markets:
            market_signals = self._analyze_market(market)
            signals.extend(market_signals)

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return [s for s in signals if s.confidence >= self.config.min_confidence]

    def _analyze_market(self, market: Market) -> list[TradingSignal]:
        signals: list[TradingSignal] = []

        mispricing = self._detect_mispricing(market)
        if mispricing is not None:
            signals.append(mispricing)

        extreme = self._detect_extreme_values(market)
        if extreme is not None:
            signals.append(extreme)

        volume_signal = self._detect_volume_anomaly(market)
        if volume_signal is not None:
            signals.append(volume_signal)

        return signals

    def _detect_mispricing(self, market: Market) -> TradingSignal | None:
        if len(market.tokens) < 2:
            return None

        yes_price = market.yes_price
        no_price = market.no_price
        if yes_price <= 0 or no_price <= 0:
            return None

        price_sum = yes_price + no_price
        deviation = abs(1.0 - price_sum)

        if deviation < 0.02:
            return None

        if price_sum > 1.02:
            cheaper_side = "YES" if yes_price < no_price else "NO"
            cheaper_price = min(yes_price, no_price)
            fair_value = 1.0 - max(yes_price, no_price)
            ev = fair_value - cheaper_price

            confidence = min(deviation * 5, 0.95)
            strength = self._confidence_to_strength(confidence)

            return TradingSignal(
                signal_type=SignalType.OVERVALUED,
                strength=strength,
                market=market,
                confidence=confidence,
                recommended_side=cheaper_side,
                recommended_price=cheaper_price,
                expected_value=ev,
                reason=f"Price sum {price_sum:.3f} > 1.0, {cheaper_side} side underpriced",
                risk_score=0.4,
            )

        if price_sum < 0.98:
            better_side = "YES" if yes_price > no_price else "NO"
            better_price = max(yes_price, no_price)
            ev = 1.0 - price_sum

            confidence = min(deviation * 5, 0.95)
            strength = self._confidence_to_strength(confidence)

            return TradingSignal(
                signal_type=SignalType.UNDERVALUED,
                strength=strength,
                market=market,
                confidence=confidence,
                recommended_side=better_side,
                recommended_price=better_price,
                expected_value=ev,
                reason=f"Price sum {price_sum:.3f} < 1.0, both sides available cheaply",
                risk_score=0.3,
            )

        return None

    def _detect_extreme_values(self, market: Market) -> TradingSignal | None:
        yes_price = market.yes_price
        if yes_price <= 0:
            return None

        if yes_price >= 0.95:
            implied_prob = yes_price
            ev = 1.0 - yes_price
            confidence = 0.55 + (yes_price - 0.95) * 4
            confidence = min(confidence, 0.85)

            return TradingSignal(
                signal_type=SignalType.OVERVALUED,
                strength=SignalStrength.WEAK,
                market=market,
                confidence=confidence,
                recommended_side="NO",
                recommended_price=market.no_price,
                expected_value=ev,
                reason=(
                    f"YES at {implied_prob:.1%} — contrarian NO"
                    " if fundamentals disagree"
                ),
                risk_score=0.7,
            )

        if yes_price <= 0.05:
            ev = yes_price
            confidence = 0.55 + (0.05 - yes_price) * 4
            confidence = min(confidence, 0.85)

            return TradingSignal(
                signal_type=SignalType.UNDERVALUED,
                strength=SignalStrength.WEAK,
                market=market,
                confidence=confidence,
                recommended_side="YES",
                recommended_price=yes_price,
                expected_value=ev,
                reason=f"YES at {yes_price:.1%} — high payout if event occurs (long-shot value)",
                risk_score=0.8,
            )

        return None

    def _detect_volume_anomaly(self, market: Market) -> TradingSignal | None:
        if market.volume <= 0 or market.volume_24h <= 0:
            return None

        avg_daily_volume = market.volume / max(self._estimate_market_age_days(market), 1)
        if avg_daily_volume <= 0:
            return None

        volume_ratio = market.volume_24h / avg_daily_volume

        if volume_ratio < 3.0:
            return None

        yes_price = market.yes_price
        if yes_price <= 0:
            return None

        side = "YES" if yes_price > 0.5 else "NO"
        price = yes_price if side == "YES" else market.no_price

        confidence = min(0.5 + math.log2(volume_ratio) * 0.1, 0.85)
        strength = self._confidence_to_strength(confidence)

        # Momentum implies price will continue in the current direction.
        # Estimate EV as a fraction of the remaining distance to 1.0.
        momentum_edge = min(volume_ratio * 0.005, 0.05)
        ev = momentum_edge * (1.0 - price) if price < 1.0 else 0.0

        return TradingSignal(
            signal_type=SignalType.MOMENTUM,
            strength=strength,
            market=market,
            confidence=confidence,
            recommended_side=side,
            recommended_price=price,
            expected_value=ev,
            reason=f"24h volume {volume_ratio:.1f}x above average — momentum signal",
            risk_score=0.6,
        )

    def _estimate_market_age_days(self, market: Market) -> int:
        if not market.end_date:
            return 30
        try:
            end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
            now = datetime.now(tz=timezone.utc)
            remaining = (end - now).days
            total_estimated = remaining + 30
            return max(total_estimated, 1)
        except (ValueError, TypeError):
            return 30

    def _confidence_to_strength(self, confidence: float) -> SignalStrength:
        if confidence >= self.config.strong_signal_threshold:
            return SignalStrength.STRONG
        if confidence >= 0.65:
            return SignalStrength.MEDIUM
        return SignalStrength.WEAK
