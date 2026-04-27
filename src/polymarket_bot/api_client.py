"""Polymarket API client for CLOB and Gamma endpoints."""

from __future__ import annotations

import time
from typing import Any

import httpx

from polymarket_bot.config import Config
from polymarket_bot.models import Market, OrderBook, OrderBookLevel, Token


class PolymarketClient:
    """Client for Polymarket public APIs (CLOB + Gamma)."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._http = httpx.Client(timeout=30.0, follow_redirects=True)
        self._last_request_time = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.request_delay_sec:
            time.sleep(self.config.request_delay_sec - elapsed)
        self._last_request_time = time.time()

    # ── Gamma API (market metadata) ────────────────────────────────

    def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        order: str = "volume24hr",
        ascending: bool = False,
        tag: str | None = None,
    ) -> list[Market]:
        self._rate_limit()
        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if tag:
            params["tag"] = tag

        resp = self._http.get(f"{self.config.gamma_host}/markets", params=params)
        resp.raise_for_status()
        return [self._parse_market(m) for m in resp.json()]

    def get_all_active_markets(self, max_markets: int | None = None) -> list[Market]:
        all_markets: list[Market] = []
        offset = 0
        batch_size = 100
        limit = max_markets or self.config.max_markets_per_scan

        while len(all_markets) < limit:
            batch = self.get_markets(limit=batch_size, offset=offset)
            if not batch:
                break
            all_markets.extend(batch)
            offset += batch_size
            if len(batch) < batch_size:
                break

        return all_markets[:limit]

    def get_events(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        order: str = "volume24hr",
        ascending: bool = False,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        self._rate_limit()
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if tag:
            params["tag"] = tag

        resp = self._http.get(f"{self.config.gamma_host}/events", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── CLOB API (orderbook / prices) ──────────────────────────────

    def get_order_book(self, token_id: str) -> OrderBook:
        self._rate_limit()
        resp = self._http.get(
            f"{self.config.clob_host}/book", params={"token_id": token_id}
        )
        resp.raise_for_status()
        data = resp.json()

        bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in data.get("asks", [])
        ]

        best_bid = bids[0].price if bids else 0.0
        best_ask = asks[0].price if asks else 1.0
        spread = best_ask - best_bid
        midpoint = (best_bid + best_ask) / 2.0

        return OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            midpoint=midpoint,
        )

    def get_midpoint(self, token_id: str) -> float:
        self._rate_limit()
        resp = self._http.get(
            f"{self.config.clob_host}/midpoint", params={"token_id": token_id}
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0.0))

    def get_price(self, token_id: str, side: str = "buy") -> float:
        self._rate_limit()
        resp = self._http.get(
            f"{self.config.clob_host}/price",
            params={"token_id": token_id, "side": side},
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0.0))

    def get_prices(self, market: Market) -> dict[str, float]:
        prices: dict[str, float] = {}
        for token in market.tokens:
            try:
                prices[token.outcome] = self.get_midpoint(token.token_id)
            except httpx.HTTPError:
                prices[token.outcome] = token.price
        return prices

    # ── Parsing helpers ────────────────────────────────────────────

    def _parse_market(self, data: dict[str, Any]) -> Market:
        tokens: list[Token] = []
        for t in data.get("tokens", []):
            tokens.append(
                Token(
                    token_id=t.get("token_id", ""),
                    outcome=t.get("outcome", ""),
                    price=float(t.get("price", 0)),
                    winner=bool(t.get("winner", False)),
                )
            )

        return Market(
            condition_id=data.get("condition_id", ""),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            tokens=tokens,
            volume=float(data.get("volume", 0) or 0),
            volume_24h=float(data.get("volume24hr", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            end_date=data.get("end_date_iso", "") or "",
            active=bool(data.get("active", True)),
            closed=bool(data.get("closed", False)),
            tags=[tag.get("label", "") for tag in data.get("tags", []) if isinstance(tag, dict)],
            description=data.get("description", "") or "",
            event_slug=data.get("event_slug", "") or "",
        )
