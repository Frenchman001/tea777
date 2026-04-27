"""External data sources for probability estimation.

Compares Polymarket prices with real-world data to find mispricing.
Uses free public APIs: CoinGecko (crypto), Open-Meteo (weather).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0


@dataclass
class ExternalSignal:
    source: str
    market_slug: str
    market_question: str
    polymarket_price: float
    estimated_probability: float
    edge: float
    recommended_side: str
    reasoning: str

    @property
    def has_edge(self) -> bool:
        return abs(self.edge) > 0.03


class CryptoDataProvider:
    """Fetches real-time crypto prices from CoinGecko (free, no API key)."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=REQUEST_TIMEOUT)
        self._cache: dict[str, float] = {}

    def close(self) -> None:
        self._http.close()

    def get_price(self, coin_id: str = "bitcoin", vs: str = "usd") -> float | None:
        """Get current price for a coin."""
        cache_key = f"{coin_id}:{vs}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = self._http.get(
                f"{self.BASE_URL}/simple/price",
                params={"ids": coin_id, "vs_currencies": vs},
            )
            resp.raise_for_status()
            data = resp.json()
            price = data.get(coin_id, {}).get(vs)
            if price is not None:
                self._cache[cache_key] = float(price)
                return float(price)
        except Exception as e:
            logger.debug("CoinGecko fetch failed for %s: %s", coin_id, e)
        return None

    def analyze_crypto_market(self, market: Market) -> ExternalSignal | None:
        """Compare a crypto-related Polymarket market with real prices."""
        q = market.question.lower()

        # Extract target price from question (e.g., "Will Bitcoin reach $100,000?")
        price_match = re.search(r"\$([0-9,]+(?:\.\d+)?)[kK]?", market.question)
        if not price_match:
            return None

        target_str = price_match.group(1).replace(",", "")
        try:
            target_price = float(target_str)
        except ValueError:
            return None

        if "k" in market.question[price_match.end():price_match.end() + 2].lower():
            target_price *= 1000

        coin_id = "bitcoin"
        if any(w in q for w in ["ethereum", "eth "]):
            coin_id = "ethereum"
        elif any(w in q for w in ["solana", "sol "]):
            coin_id = "solana"
        elif not any(w in q for w in ["bitcoin", "btc"]):
            return None

        current_price = self.get_price(coin_id)
        if current_price is None:
            return None

        # Estimate probability based on distance to target
        is_above = any(w in q for w in ["reach", "above", "hit", "over", "exceed"])
        is_below = any(w in q for w in ["dip", "below", "under", "drop", "fall"])

        if is_above:
            ratio = current_price / target_price
            if ratio >= 1.0:
                est_prob = 0.92
            elif ratio > 0.95:
                est_prob = 0.7 + (ratio - 0.95) * 4.4
            elif ratio > 0.85:
                est_prob = 0.35 + (ratio - 0.85) * 3.5
            elif ratio > 0.70:
                est_prob = 0.10 + (ratio - 0.70) * 1.67
            else:
                est_prob = max(0.02, ratio * 0.14)
        elif is_below:
            ratio = target_price / current_price
            if ratio >= 1.0:
                est_prob = 0.92
            elif ratio > 0.95:
                est_prob = 0.7 + (ratio - 0.95) * 4.4
            elif ratio > 0.85:
                est_prob = 0.35 + (ratio - 0.85) * 3.5
            else:
                est_prob = max(0.02, ratio * 0.14)
        else:
            return None

        poly_price = market.yes_price
        edge = est_prob - poly_price

        if abs(edge) < 0.03:
            return None

        side = "YES" if edge > 0 else "NO"

        return ExternalSignal(
            source=f"CoinGecko ({coin_id})",
            market_slug=market.slug,
            market_question=market.question,
            polymarket_price=poly_price,
            estimated_probability=round(est_prob, 3),
            edge=round(edge, 3),
            recommended_side=side,
            reasoning=(
                f"{coin_id.title()} current: ${current_price:,.0f}, "
                f"target: ${target_price:,.0f}, "
                f"estimated prob: {est_prob:.0%} vs Polymarket: {poly_price:.0%}"
            ),
        )


class WeatherDataProvider:
    """Fetches weather data from Open-Meteo (free, no API key)."""

    BASE_URL = "https://api.open-meteo.com/v1"

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=REQUEST_TIMEOUT)

    def close(self) -> None:
        self._http.close()

    def get_temperature(
        self, latitude: float = 40.71, longitude: float = -74.01,
    ) -> float | None:
        """Get current temperature for a location (default: NYC)."""
        try:
            resp = self._http.get(
                f"{self.BASE_URL}/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current_weather": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("current_weather", {}).get("temperature")
        except Exception as e:
            logger.debug("Open-Meteo fetch failed: %s", e)
            return None


class ExternalDataAggregator:
    """Aggregates signals from all external data sources."""

    def __init__(self) -> None:
        self.crypto = CryptoDataProvider()
        self.weather = WeatherDataProvider()

    def close(self) -> None:
        self.crypto.close()
        self.weather.close()

    def analyze_markets(self, markets: list[Market]) -> list[ExternalSignal]:
        """Analyze all markets against external data sources."""
        signals: list[ExternalSignal] = []

        for market in markets:
            q = market.question.lower()

            if any(w in q for w in ["bitcoin", "btc", "ethereum", "eth", "solana"]):
                sig = self.crypto.analyze_crypto_market(market)
                if sig and sig.has_edge:
                    signals.append(sig)

        signals.sort(key=lambda s: abs(s.edge), reverse=True)
        return signals
