"""WebSocket real-time price stream for instant arbitrage detection.

Connects to Polymarket WebSocket API for live price updates.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class PriceUpdate:
    token_id: str
    price: float
    timestamp: float
    side: str = ""


@dataclass
class ArbitrageAlert:
    market_question: str
    yes_price: float
    no_price: float
    price_sum: float
    profit_pct: float
    detected_at: float


class PriceStreamManager:
    """Manages WebSocket connections for real-time price monitoring.

    Uses httpx-ws or falls back to websocket-client for connectivity.
    """

    def __init__(self) -> None:
        self._prices: dict[str, float] = {}
        self._market_tokens: dict[str, dict[str, str]] = {}
        self._callbacks: list = []
        self._running = False
        self._lock = threading.Lock()
        self._alerts: list[ArbitrageAlert] = []

    def register_market(
        self,
        market_slug: str,
        question: str,
        yes_token_id: str,
        no_token_id: str,
    ) -> None:
        """Register a market for price monitoring."""
        self._market_tokens[market_slug] = {
            "question": question,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
        }

    def on_alert(self, callback: object) -> None:
        """Register a callback for arbitrage alerts."""
        self._callbacks.append(callback)

    def update_price(self, token_id: str, price: float) -> None:
        """Update a token price and check for arbitrage."""
        with self._lock:
            self._prices[token_id] = price

        for slug, tokens in self._market_tokens.items():
            if token_id in (tokens["yes_token_id"], tokens["no_token_id"]):
                self._check_arbitrage(slug, tokens)

    def _check_arbitrage(self, slug: str, tokens: dict[str, str]) -> None:
        yes_id = tokens["yes_token_id"]
        no_id = tokens["no_token_id"]

        with self._lock:
            yes_price = self._prices.get(yes_id)
            no_price = self._prices.get(no_id)

        if yes_price is None or no_price is None:
            return

        price_sum = yes_price + no_price
        if price_sum < 0.995:
            profit_pct = (1.0 - price_sum) * 100
            alert = ArbitrageAlert(
                market_question=tokens["question"],
                yes_price=yes_price,
                no_price=no_price,
                price_sum=price_sum,
                profit_pct=profit_pct,
                detected_at=time.time(),
            )
            self._alerts.append(alert)
            for cb in self._callbacks:
                try:
                    cb(alert)
                except Exception:
                    logger.debug("Callback error for alert on %s", slug)

    def get_recent_alerts(self, max_age_sec: float = 300) -> list[ArbitrageAlert]:
        """Return alerts from the last N seconds."""
        cutoff = time.time() - max_age_sec
        return [a for a in self._alerts if a.detected_at >= cutoff]

    def start_polling(
        self,
        client: object,
        interval: float = 5.0,
        max_iterations: int | None = None,
    ) -> None:
        """Fallback polling mode when WebSocket is unavailable.

        Periodically fetches prices from the REST API and checks for arb.
        """
        self._running = True
        iteration = 0

        while self._running:
            if max_iterations is not None and iteration >= max_iterations:
                break

            for slug, tokens in self._market_tokens.items():
                try:
                    yes_price = client.get_price(tokens["yes_token_id"], "buy")
                    no_price = client.get_price(tokens["no_token_id"], "buy")
                    self.update_price(tokens["yes_token_id"], yes_price)
                    self.update_price(tokens["no_token_id"], no_price)
                except Exception:
                    logger.debug("Price fetch failed for %s", slug)

            time.sleep(interval)
            iteration += 1

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False

    def start_websocket(self, token_ids: list[str]) -> None:
        """Start WebSocket connection for real-time updates.

        Requires the `websockets` package. Falls back to polling if unavailable.
        """
        try:
            import asyncio

            import websockets
        except ImportError:
            logger.warning("websockets package not installed, use polling mode instead")
            return

        async def _connect() -> None:
            try:
                async with websockets.connect(WS_URL) as ws:
                    subscribe_msg = json.dumps({
                        "type": "subscribe",
                        "channel": "market",
                        "assets_ids": token_ids,
                    })
                    await ws.send(subscribe_msg)
                    logger.info("WebSocket connected, subscribed to %d tokens", len(token_ids))

                    self._running = True
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(msg)
                            self._handle_ws_message(data)
                        except asyncio.TimeoutError:
                            continue
                        except Exception as e:
                            logger.debug("WebSocket message error: %s", e)
                            break
            except Exception as e:
                logger.warning("WebSocket connection failed: %s", e)

        try:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_until_complete, args=(_connect(),))
            thread.daemon = True
            thread.start()
        except Exception:
            logger.warning("Failed to start WebSocket thread")

    def _handle_ws_message(self, data: dict) -> None:
        """Process incoming WebSocket price update."""
        if not isinstance(data, dict):
            return

        asset_id = data.get("asset_id", "")
        price = data.get("price")

        if asset_id and price is not None:
            try:
                self.update_price(asset_id, float(price))
            except (ValueError, TypeError):
                pass


def create_price_monitor(
    markets: list,
) -> PriceStreamManager:
    """Create a PriceStreamManager pre-loaded with market data."""
    manager = PriceStreamManager()

    for m in markets:
        yes_id = m.yes_token_id
        no_id = m.no_token_id
        if yes_id and no_id:
            manager.register_market(
                market_slug=m.slug,
                question=m.question,
                yes_token_id=yes_id,
                no_token_id=no_id,
            )

    return manager
