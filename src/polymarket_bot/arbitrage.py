"""Arbitrage scanner for Polymarket markets."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.config import Config
from polymarket_bot.models import ArbitrageOpportunity, Market, parse_json_field

logger = logging.getLogger(__name__)


class ArbitrageScanner:
    """Scans Polymarket for arbitrage opportunities where YES + NO < 1.0."""

    def __init__(self, client: PolymarketClient, config: Config | None = None) -> None:
        self.client = client
        self.config = config or Config()

    def scan(self, markets: list[Market] | None = None) -> list[ArbitrageOpportunity]:
        if markets is None:
            markets = self.client.get_all_active_markets()

        opportunities: list[ArbitrageOpportunity] = []
        for market in markets:
            opp = self._check_market(market)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)
        return opportunities

    def scan_with_orderbook(
        self, markets: list[Market] | None = None,
    ) -> list[ArbitrageOpportunity]:
        if markets is None:
            markets = self.client.get_all_active_markets()

        opportunities: list[ArbitrageOpportunity] = []
        for market in markets:
            opp = self._check_market_orderbook(market)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)
        return opportunities

    def _check_market(self, market: Market) -> ArbitrageOpportunity | None:
        if not market.active or market.closed:
            return None
        if len(market.tokens) < 2:
            return None
        if market.volume_24h < self.config.min_volume_24h:
            return None

        yes_price = market.yes_price
        no_price = market.no_price
        if yes_price <= 0 or no_price <= 0:
            return None

        price_sum = yes_price + no_price
        if price_sum >= self.config.max_price_sum:
            return None

        profit_pct = (1.0 - price_sum) * 100
        if profit_pct < self.config.min_profit_pct:
            return None

        guaranteed_profit = 1.0 - price_sum
        liquidity_score = self._calculate_liquidity_score(market)

        return ArbitrageOpportunity(
            market=market,
            price_sum=price_sum,
            profit_pct=profit_pct,
            buy_yes_price=yes_price,
            buy_no_price=no_price,
            guaranteed_profit=guaranteed_profit,
            liquidity_score=liquidity_score,
        )

    def _check_market_orderbook(self, market: Market) -> ArbitrageOpportunity | None:
        if not market.active or market.closed:
            return None
        if len(market.tokens) < 2:
            return None

        yes_id = market.yes_token_id
        no_id = market.no_token_id
        if not yes_id or not no_id:
            return None

        try:
            yes_book = self.client.get_order_book(yes_id)
            no_book = self.client.get_order_book(no_id)
        except Exception:
            logger.debug("Failed to fetch orderbook for %s", market.slug)
            return None

        best_ask_yes = yes_book.best_ask
        best_ask_no = no_book.best_ask
        if best_ask_yes <= 0 or best_ask_no <= 0:
            return None

        price_sum = best_ask_yes + best_ask_no
        if price_sum >= self.config.max_price_sum:
            return None

        profit_pct = (1.0 - price_sum) * 100
        if profit_pct < self.config.min_profit_pct:
            return None

        yes_depth = sum(a.size for a in yes_book.asks[:3])
        no_depth = sum(a.size for a in no_book.asks[:3])
        liquidity_score = min(yes_depth, no_depth) / 1000.0

        return ArbitrageOpportunity(
            market=market,
            price_sum=price_sum,
            profit_pct=profit_pct,
            buy_yes_price=best_ask_yes,
            buy_no_price=best_ask_no,
            guaranteed_profit=1.0 - price_sum,
            liquidity_score=min(liquidity_score, 1.0),
        )

    def _calculate_liquidity_score(self, market: Market) -> float:
        if market.liquidity <= 0:
            return 0.0
        score = min(market.liquidity / 50000.0, 1.0)
        return round(score, 3)


class MultiOutcomeArbitrageScanner:
    """Scans multi-outcome events for arbitrage (sum of all outcomes < 1.0)."""

    def __init__(self, client: PolymarketClient, config: Config | None = None) -> None:
        self.client = client
        self.config = config or Config()

    def scan_events(self) -> list[dict]:
        events = self.client.get_events(limit=100, active=True, closed=False)
        opportunities: list[dict] = []

        for event in events:
            opp = self._check_event(event)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o["profit_pct"], reverse=True)
        return opportunities

    def _check_event(self, event: dict) -> dict | None:
        markets_data = event.get("markets", [])
        if len(markets_data) < 2:
            return None

        total_price = 0.0
        market_prices: list[dict] = []
        for m in markets_data:
            yes_price = self._extract_yes_price(m)
            total_price += yes_price
            market_prices.append({
                "question": m.get("question", ""),
                "yes_price": yes_price,
                "slug": m.get("slug", ""),
            })

        if total_price <= 0 or total_price >= self.config.max_price_sum:
            return None

        profit_pct = (1.0 - total_price) * 100
        if profit_pct < self.config.min_profit_pct:
            return None

        now = datetime.now(tz=timezone.utc)
        end_str = event.get("endDateIso", event.get("end_date_iso", ""))
        remaining_days = None
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                remaining_days = (end_dt - now).days
            except (ValueError, TypeError):
                pass

        return {
            "event_title": event.get("title", ""),
            "event_slug": event.get("slug", ""),
            "total_price": total_price,
            "profit_pct": profit_pct,
            "num_outcomes": len(markets_data),
            "markets": market_prices,
            "remaining_days": remaining_days,
        }

    def _extract_yes_price(self, market_data: dict) -> float:
        outcomes = parse_json_field(market_data.get("outcomes"))
        prices = parse_json_field(market_data.get("outcomePrices"))
        if outcomes and prices:
            for i, outcome in enumerate(outcomes):
                if outcome.upper() == "YES" and i < len(prices):
                    return float(prices[i] or 0)
            return 0.0

        for t in market_data.get("tokens", []):
            if t.get("outcome", "").upper() == "YES":
                return float(t.get("price", 0) or 0)
        return 0.0


