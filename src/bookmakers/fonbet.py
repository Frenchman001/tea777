"""Fonbet bookmaker parser.

Fonbet exposes a JSON API used by their web frontend.
Endpoints are subject to change — keep URL patterns up to date.
"""

from datetime import datetime

from loguru import logger

from src.bookmakers.base import BookmakerParser
from src.config import settings
from src.models.events import (
    BookmakerOdds,
    Outcome,
    OutcomeType,
    SportEvent,
    SportType,
)

FONBET_SPORT_IDS: dict[SportType, list[int]] = {
    SportType.FOOTBALL: [1],
    SportType.BASKETBALL: [3],
    SportType.TENNIS: [5],
    SportType.HOCKEY: [2],
    SportType.MMA: [146],
    SportType.BOXING: [9],
}


class FonbetParser(BookmakerParser):
    name = "Fonbet"
    base_url = settings.fonbet_base_url

    async def fetch_sports_events(
        self, sport: SportType | None = None
    ) -> list[BookmakerOdds]:
        """Fetch prematch events from Fonbet's internal API."""
        results: list[BookmakerOdds] = []

        sport_ids: list[int] = []
        if sport and sport in FONBET_SPORT_IDS:
            sport_ids = FONBET_SPORT_IDS[sport]
        else:
            for ids in FONBET_SPORT_IDS.values():
                sport_ids.extend(ids)

        for sport_id in sport_ids:
            events = await self._fetch_sport(sport_id)
            results.extend(events)

        logger.info(f"Fonbet: fetched {len(results)} events")
        return results

    async def _fetch_sport(self, sport_id: int) -> list[BookmakerOdds]:
        """Fetch events for a specific sport ID."""
        url = f"{self.base_url}/api/v2/prematch"
        params = {
            "sport": sport_id,
            "lang": "ru",
        }

        data = await self._safe_request(url, params)
        if not data or not isinstance(data, dict):
            # Fallback: try the line endpoint
            url = f"{self.base_url}/line/api/v1/prematch"
            data = await self._safe_request(url, params)

        if not data or not isinstance(data, dict):
            return []

        return self._parse_events(data, sport_id)

    def _parse_events(self, data: dict, sport_id: int) -> list[BookmakerOdds]:
        """Parse Fonbet API response into BookmakerOdds."""
        results: list[BookmakerOdds] = []
        events = data.get("events", data.get("data", {}).get("events", []))

        sport = self._sport_from_id(sport_id)

        for event in events:
            try:
                parsed = self._parse_single_event(event, sport)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.debug(f"Fonbet: skip event: {e}")

        return results

    def _parse_single_event(
        self, event: dict, sport: SportType
    ) -> BookmakerOdds | None:
        """Parse a single Fonbet event."""
        event_id = str(event.get("id", ""))
        name = event.get("name", "")
        teams = event.get("teams", [])

        if len(teams) < 2:
            parts = name.split(" - ")
            if len(parts) < 2:
                return None
            home, away = parts[0].strip(), parts[1].strip()
        else:
            home = teams[0].get("name", "")
            away = teams[1].get("name", "")

        if not home or not away:
            return None

        start_time = None
        ts = event.get("startTime", event.get("start_time"))
        if ts:
            try:
                start_time = datetime.fromtimestamp(int(ts))
            except (ValueError, TypeError, OSError):
                pass

        sport_event = SportEvent(
            event_id=f"fonbet_{event_id}",
            sport=sport,
            league=event.get("tournament", {}).get("name", ""),
            home_team=home,
            away_team=away,
            start_time=start_time,
        )

        outcomes: list[Outcome] = []
        markets = event.get("markets", event.get("bets", []))

        for market in markets:
            market_type = market.get("type", market.get("betType", ""))
            selections = market.get("selections", market.get("outcomes", []))

            if market_type in ("1X2", "winner", "12", "1x2"):
                for sel in selections:
                    odds_val = float(sel.get("odds", sel.get("value", 0)))
                    if odds_val < 1.01:
                        continue
                    sel_name = sel.get("name", sel.get("shortName", ""))
                    otype = self._map_outcome_type(sel_name, sel.get("type", ""))
                    if otype:
                        outcomes.append(Outcome.from_odds(sel_name, otype, odds_val))

        if not outcomes:
            return None

        return BookmakerOdds(
            bookmaker=self.name,
            event=sport_event,
            outcomes=outcomes,
            url=f"{self.base_url}/sports/{sport_event.event_id}",
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def _map_outcome_type(name: str, sel_type: str) -> OutcomeType | None:
        name_lower = name.lower()
        if sel_type in ("1", "home") or "п1" in name_lower or name_lower == "1":
            return OutcomeType.WIN_HOME
        if sel_type in ("2", "away") or "п2" in name_lower or name_lower == "2":
            return OutcomeType.WIN_AWAY
        if sel_type == "X" or "ничья" in name_lower or name_lower == "x":
            return OutcomeType.DRAW
        return None

    @staticmethod
    def _sport_from_id(sport_id: int) -> SportType:
        for sport, ids in FONBET_SPORT_IDS.items():
            if sport_id in ids:
                return sport
        return SportType.OTHER
