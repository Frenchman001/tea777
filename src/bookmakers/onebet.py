"""1xBet bookmaker parser.

1xBet uses a JSON API behind their SPA frontend.
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

ONEBET_SPORT_IDS: dict[SportType, int] = {
    SportType.FOOTBALL: 1,
    SportType.BASKETBALL: 3,
    SportType.TENNIS: 5,
    SportType.HOCKEY: 2,
    SportType.MMA: 148,
    SportType.BOXING: 56,
}


class OnexbetParser(BookmakerParser):
    name = "1xBet"
    base_url = settings.onebet_base_url

    async def fetch_sports_events(
        self, sport: SportType | None = None
    ) -> list[BookmakerOdds]:
        """Fetch prematch events from 1xBet API."""
        results: list[BookmakerOdds] = []

        sport_ids: dict[SportType, int] = {}
        if sport and sport in ONEBET_SPORT_IDS:
            sport_ids = {sport: ONEBET_SPORT_IDS[sport]}
        else:
            sport_ids = ONEBET_SPORT_IDS

        for sp, sid in sport_ids.items():
            events = await self._fetch_sport(sid, sp)
            results.extend(events)

        logger.info(f"1xBet: fetched {len(results)} events")
        return results

    async def _fetch_sport(
        self, sport_id: int, sport: SportType
    ) -> list[BookmakerOdds]:
        """Fetch events for a specific sport."""
        url = f"{self.base_url}/LineFeed/GetSportsShortZip"
        params = {
            "sports": sport_id,
            "count": 50,
            "lng": "ru",
            "mode": 4,
            "country": 1,
            "getEmpty": "true",
        }

        data = await self._safe_request(url, params)
        if not data:
            # Fallback
            url = f"{self.base_url}/LineFeed/Get1x2_VZip"
            params = {"sports": sport_id, "count": 50, "lng": "ru"}
            data = await self._safe_request(url, params)

        if not data:
            return []

        return self._parse_response(data, sport)

    def _parse_response(
        self, data: dict | list, sport: SportType
    ) -> list[BookmakerOdds]:
        """Parse 1xBet API response."""
        results: list[BookmakerOdds] = []

        if isinstance(data, dict):
            events = data.get("Value", data.get("events", []))
        elif isinstance(data, list):
            events = data
        else:
            return []

        for event in events:
            try:
                parsed = self._parse_event(event, sport)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.debug(f"1xBet: skip event: {e}")

        return results

    def _parse_event(
        self, event: dict, sport: SportType
    ) -> BookmakerOdds | None:
        """Parse a single 1xBet event."""
        event_id = str(event.get("CI", event.get("id", "")))
        name = event.get("L", event.get("name", ""))

        opp1 = event.get("O1", "")
        opp2 = event.get("O2", "")

        if opp1 and opp2:
            home, away = str(opp1), str(opp2)
        else:
            parts = str(name).split(" - ")
            if len(parts) < 2:
                return None
            home, away = parts[0].strip(), parts[1].strip()

        if not home or not away:
            return None

        start_time = None
        ts = event.get("S", event.get("startTime"))
        if ts:
            try:
                start_time = datetime.fromtimestamp(int(ts))
            except (ValueError, TypeError, OSError):
                pass

        league = event.get("L2", event.get("league", ""))

        sport_event = SportEvent(
            event_id=f"1xbet_{event_id}",
            sport=sport,
            league=str(league),
            home_team=home,
            away_team=away,
            start_time=start_time,
        )

        outcomes = self._extract_outcomes(event)
        if not outcomes:
            return None

        return BookmakerOdds(
            bookmaker=self.name,
            event=sport_event,
            outcomes=outcomes,
            url=f"{self.base_url}/line/{event_id}",
            fetched_at=datetime.utcnow(),
        )

    def _extract_outcomes(self, event: dict) -> list[Outcome]:
        """Extract main market outcomes."""
        outcomes: list[Outcome] = []

        # 1xBet format: E list with individual events/odds
        events_data = event.get("E", event.get("GE", []))
        if isinstance(events_data, list):
            for e in events_data:
                group = e.get("G", e.get("group", 0))
                if group not in (1, 2):
                    continue
                coefs = e.get("C", e.get("coeff", 0))
                sel_type = e.get("T", e.get("type", 0))
                if isinstance(coefs, (int, float)) and coefs >= 1.01:
                    otype = self._map_outcome_type(sel_type)
                    if otype:
                        name = self._outcome_name(sel_type)
                        outcomes.append(Outcome.from_odds(name, otype, float(coefs)))

        # Alternative format
        if not outcomes:
            for key, otype in [("W1", OutcomeType.WIN_HOME), ("WX", OutcomeType.DRAW),
                               ("W2", OutcomeType.WIN_AWAY)]:
                val = event.get(key, 0)
                if isinstance(val, (int, float)) and val >= 1.01:
                    outcomes.append(Outcome.from_odds(key, otype, float(val)))

        return outcomes

    @staticmethod
    def _map_outcome_type(sel_type: int) -> OutcomeType | None:
        mapping = {
            1: OutcomeType.WIN_HOME,
            2: OutcomeType.DRAW,
            3: OutcomeType.WIN_AWAY,
        }
        return mapping.get(sel_type)

    @staticmethod
    def _outcome_name(sel_type: int) -> str:
        names = {1: "1", 2: "X", 3: "2"}
        return names.get(sel_type, str(sel_type))
