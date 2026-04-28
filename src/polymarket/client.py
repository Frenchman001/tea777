"""Polymarket API client for fetching sports markets and prices."""

import asyncio
from datetime import datetime

import aiohttp
from loguru import logger

from src.config import settings
from src.models.events import (
    Outcome,
    OutcomeType,
    PolymarketMarket,
    SportType,
)

SPORT_KEYWORDS: dict[SportType, list[str]] = {
    SportType.FOOTBALL: [
        "nfl", "football", "soccer", "premier league", "champions league",
        "world cup", "la liga", "bundesliga", "serie a", "ligue 1",
        "mls", "epl", "uefa", "fifa",
    ],
    SportType.BASKETBALL: [
        "nba", "basketball", "ncaa basketball", "euroleague", "wnba",
    ],
    SportType.TENNIS: [
        "tennis", "atp", "wta", "grand slam", "wimbledon",
        "us open tennis", "french open", "australian open",
    ],
    SportType.HOCKEY: [
        "nhl", "hockey", "khl", "ice hockey",
    ],
    SportType.MMA: [
        "ufc", "mma", "bellator", "pfl", "mixed martial arts",
    ],
    SportType.BOXING: [
        "boxing", "wbc", "wba", "ibf", "wbo",
    ],
    SportType.ESPORTS: [
        "esports", "cs2", "csgo", "dota", "league of legends", "valorant",
    ],
}


def classify_sport(text: str) -> SportType:
    text_lower = text.lower()
    for sport, keywords in SPORT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return sport
    return SportType.OTHER


def extract_outcomes(market_data: dict) -> list[Outcome]:
    outcomes: list[Outcome] = []
    tokens = market_data.get("tokens", [])

    if len(tokens) == 2:
        for token in tokens:
            outcome_str = token.get("outcome", "").lower()
            price = float(token.get("price", 0))
            if price <= 0:
                continue

            if outcome_str in ("yes", "true", "1"):
                otype = OutcomeType.YES
            elif outcome_str in ("no", "false", "0"):
                otype = OutcomeType.NO
            else:
                otype = OutcomeType.YES if tokens.index(token) == 0 else OutcomeType.NO

            outcomes.append(Outcome.from_probability(
                name=token.get("outcome", outcome_str),
                outcome_type=otype,
                prob=price,
            ))
    elif len(tokens) > 2:
        for i, token in enumerate(tokens):
            price = float(token.get("price", 0))
            if price <= 0:
                continue
            if i == 0:
                otype = OutcomeType.WIN_HOME
            elif i == 1:
                otype = OutcomeType.WIN_AWAY
            else:
                otype = OutcomeType.DRAW
            outcomes.append(Outcome.from_probability(
                name=token.get("outcome", f"outcome_{i}"),
                outcome_type=otype,
                prob=price,
            ))

    return outcomes


class PolymarketClient:
    """Client for Polymarket Gamma API to fetch sports markets."""

    def __init__(self) -> None:
        self.gamma_url = settings.polymarket_gamma_url
        self.clob_url = settings.polymarket_api_url
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_sports_markets(
        self, limit: int = 100, active_only: bool = True
    ) -> list[PolymarketMarket]:
        """Fetch sports-related markets from Polymarket Gamma API."""
        session = await self._get_session()
        markets: list[PolymarketMarket] = []

        sport_tags = ["sports", "nba", "nfl", "ufc", "soccer", "tennis", "hockey", "mma"]

        tasks = [self._fetch_markets_by_tag(session, tag, limit) for tag in sport_tags]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_ids: set[str] = set()
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch markets: {result}")
                continue
            for market in result:
                if market.condition_id not in seen_ids:
                    if not active_only or market.active:
                        seen_ids.add(market.condition_id)
                        markets.append(market)

        logger.info(f"Fetched {len(markets)} unique sports markets from Polymarket")
        return markets

    async def _fetch_markets_by_tag(
        self, session: aiohttp.ClientSession, tag: str, limit: int
    ) -> list[PolymarketMarket]:
        """Fetch markets from Gamma API filtered by tag."""
        url = f"{self.gamma_url}/markets"
        params = {
            "tag": tag,
            "limit": limit,
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
        }

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"Gamma API returned {resp.status} for tag={tag}")
                    return []
                data = await resp.json()
        except Exception as e:
            logger.error(f"Error fetching markets for tag={tag}: {e}")
            return []

        markets: list[PolymarketMarket] = []
        for item in data if isinstance(data, list) else []:
            try:
                market = self._parse_market(item)
                if market:
                    markets.append(market)
            except Exception as e:
                logger.debug(f"Skipping market: {e}")

        return markets

    def _parse_market(self, data: dict) -> PolymarketMarket | None:
        """Parse raw API response into PolymarketMarket model."""
        condition_id = data.get("condition_id", data.get("id", ""))
        question = data.get("question", "")

        if not condition_id or not question:
            return None

        sport = classify_sport(question + " " + data.get("description", ""))
        outcomes = extract_outcomes(data)

        end_date = None
        end_str = data.get("end_date_iso", data.get("end_date", ""))
        if end_str:
            try:
                end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return PolymarketMarket(
            condition_id=condition_id,
            question=question,
            slug=data.get("slug", ""),
            sport=sport,
            outcomes=outcomes,
            end_date=end_date,
            volume=float(data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            active=data.get("active", True),
        )

    async def get_market_orderbook(self, token_id: str) -> dict:
        """Fetch the order book for a specific token."""
        session = await self._get_session()
        url = f"{self.clob_url}/book"
        params = {"token_id": token_id}

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching orderbook for {token_id}: {e}")

        return {}

    async def get_market_price(self, token_id: str) -> float:
        """Get the best available price for a token."""
        session = await self._get_session()
        url = f"{self.clob_url}/price"
        params = {"token_id": token_id, "side": "buy"}

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data.get("price", 0))
        except Exception as e:
            logger.error(f"Error fetching price for {token_id}: {e}")

        return 0.0
