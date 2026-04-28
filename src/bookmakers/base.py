"""Base class for bookmaker parsers."""

import abc

import aiohttp
from fake_useragent import UserAgent
from loguru import logger

from src.models.events import BookmakerOdds, SportType


class BookmakerParser(abc.ABC):
    """Abstract base class for bookmaker odds parsers."""

    name: str = "base"
    base_url: str = ""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._ua = UserAgent()

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._ua.random,
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @abc.abstractmethod
    async def fetch_sports_events(
        self, sport: SportType | None = None
    ) -> list[BookmakerOdds]:
        """Fetch current odds for sports events."""
        ...

    async def _safe_request(
        self, url: str, params: dict | None = None
    ) -> dict | list | None:
        """Make a safe HTTP request with error handling."""
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"{self.name}: HTTP {resp.status} from {url}")
        except aiohttp.ContentTypeError:
            session = await self._get_session()
            try:
                async with session.get(url, params=params) as resp:
                    text = await resp.text()
                    logger.debug(f"{self.name}: non-JSON response: {text[:200]}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"{self.name}: request error: {e}")
        return None
