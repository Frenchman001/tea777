"""Winline bookmaker parser.

Winline uses a JSON API behind their SPA frontend.
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

WINLINE_SPORT_IDS: dict[SportType, int] = {
    SportType.FOOTBALL: 1,
    SportType.BASKETBALL: 3,
    SportType.TENNIS: 5,
    SportType.HOCKEY: 2,
    SportType.MMA: 28,
    SportType.BOXING: 9,
}


class WinlineParser(BookmakerParser):
    name = "Winline"
    base_url = settings.winline_base_url

    async def fetch_sports_events(
        self, sport: SportType | None = None
    ) -> list[BookmakerOdds]:
        """Fetch prematch events from Winline API."""
        results: list[BookmakerOdds] = []

        sport_ids: dict[SportType, int] = {}
        if sport and sport in WINLINE_SPORT_IDS:
            sport_ids = {sport: WINLINE_SPORT_IDS[sport]}
        else:
            sport_ids = WINLINE_SPORT_IDS

        for sp, sid in sport_ids.items():
            events = await self._fetch_sport(sid, sp)
            results.extend(events)

        logger.info(f"Winline: fetched {len(results)} events")
        return results

    async def _fetch_sport(
        self, sport_id: int, sport: SportType
    ) -> list[BookmakerOdds]:
        """Fetch events for a specific sport."""
        url = f"{self.base_url}/api/v2/prematch/events"
        params = {
            "sportId": sport_id,
            "lang": "ru",
        }

        data = await self._safe_request(url, params)
        if not data:
            # Fallback endpoint
            url = f"{self.base_url}/core/api/v1/prematch/events"
            data = await self._safe_request(url, params)

        if not data:
            return []

        events_list = data if isinstance(data, list) else data.get("events", [])
        results: list[BookmakerOdds] = []

        for event in events_list:
            try:
                parsed = self._parse_event(event, sport)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.debug(f"Winline: skip event: {e}")

        return results

    def _parse_event(
        self, event: dict, sport: SportType
    ) -> BookmakerOdds | None:
        """Parse a single Winline event."""
        event_id = str(event.get("id", ""))
        name = event.get("name", "")
        competitors = event.get("competitors", event.get("teams", []))

        if len(competitors) >= 2:
            home = competitors[0].get("name", "")
            away = competitors[1].get("name", "")
        else:
            parts = name.split(" - ")
            if len(parts) < 2:
                return None
            home, away = parts[0].strip(), parts[1].strip()

        if not home or not away:
            return None

        start_time = None
        ts = event.get("startDate", event.get("start_time", ""))
        if ts:
            try:
                if isinstance(ts, int):
                    start_time = datetime.fromtimestamp(ts)
                else:
                    start_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except (ValueError, TypeError, OSError):
                pass

        sport_event = SportEvent(
            event_id=f"winline_{event_id}",
            sport=sport,
            league=event.get("championship", {}).get("name", ""),
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
            url=f"{self.base_url}/sports/{event_id}",
            fetched_at=datetime.utcnow(),
        )

    def _extract_outcomes(self, event: dict) -> list[Outcome]:
        """Extract 1X2 or 12 outcomes from event data."""
        outcomes: list[Outcome] = []
        markets = event.get("markets", event.get("bets", []))

        for market in markets:
            mtype = market.get("type", market.get("marketType", ""))
            if mtype not in ("1X2", "12", "winner", "match_result"):
                continue

            selections = market.get("selections", market.get("outcomes", []))
            for sel in selections:
                odds_val = float(sel.get("odds", sel.get("value", sel.get("coeff", 0))))
                if odds_val < 1.01:
                    continue
                sel_name = str(sel.get("name", sel.get("type", "")))
                otype = self._map_outcome(sel_name)
                if otype:
                    outcomes.append(Outcome.from_odds(sel_name, otype, odds_val))
            if outcomes:
                break

        return outcomes

    @staticmethod
    def _map_outcome(name: str) -> OutcomeType | None:
        n = name.lower().strip()
        if n in ("1", "п1", "home", "w1"):
            return OutcomeType.WIN_HOME
        if n in ("2", "п2", "away", "w2"):
            return OutcomeType.WIN_AWAY
        if n in ("x", "ничья", "draw"):
            return OutcomeType.DRAW
        return None
