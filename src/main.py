"""Main entry point — runs the arbitrage scanner loop."""

import asyncio
import signal
import sys

from loguru import logger

from src.arbitrage.engine import ArbitrageEngine
from src.arbitrage.matcher import EventMatcher
from src.betting.auto_bet import AutoBetter
from src.bookmakers.fonbet import FonbetParser
from src.bookmakers.onebet import OnexbetParser
from src.bookmakers.winline import WinlineParser
from src.config import settings
from src.models.events import BookmakerOdds
from src.polymarket.client import PolymarketClient
from src.telegram_bot.bot import ArbitrageBot

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)
logger.add(
    "logs/arb_bot.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
)


class ArbScanner:
    """Main scanner that orchestrates all components."""

    def __init__(self) -> None:
        self.polymarket = PolymarketClient()
        self.bookmakers = [
            FonbetParser(),
            WinlineParser(),
            OnexbetParser(),
        ]
        self.matcher = EventMatcher()
        self.engine = ArbitrageEngine()
        self.telegram = ArbitrageBot()
        self.auto_better = AutoBetter()
        self._running = False

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing Arbitrage Scanner...")
        await self.auto_better.initialize()
        await self.telegram.send_startup()
        logger.info("Scanner initialized successfully")

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self._running = False
        await self.polymarket.close()
        for bk in self.bookmakers:
            await bk.close()
        await self.telegram.close()
        await self.auto_better.initialize()  # cleanup

    async def run_scan_cycle(self) -> None:
        """Execute a single scan cycle."""
        logger.info("=" * 60)
        logger.info("Starting scan cycle...")

        # 1. Fetch Polymarket sports markets
        markets = await self.polymarket.fetch_sports_markets(limit=200)
        if not markets:
            logger.warning("No Polymarket sports markets found")
            return

        # 2. Fetch bookmaker events in parallel
        bk_tasks = [bk.fetch_sports_events() for bk in self.bookmakers]
        bk_results = await asyncio.gather(*bk_tasks, return_exceptions=True)

        all_bk_events: list[BookmakerOdds] = []
        for result in bk_results:
            if isinstance(result, Exception):
                logger.error(f"Bookmaker fetch error: {result}")
                await self.telegram.send_error(str(result))
            elif isinstance(result, list):
                all_bk_events.extend(result)

        if not all_bk_events:
            logger.warning("No bookmaker events fetched")
            return

        logger.info(
            f"Data: {len(markets)} PM markets, {len(all_bk_events)} BK events"
        )

        # 3. Match events
        matched = self.matcher.find_all_matches(markets, all_bk_events)

        # 4. Find arbitrage
        opportunities = self.engine.find_opportunities(matched)

        # 5. Send summary
        await self.telegram.send_scan_summary(
            opportunities=opportunities,
            total_markets=len(markets),
            total_bk_events=len(all_bk_events),
            matched_pairs=len(matched),
        )

        # 6. Auto-bet if enabled
        if opportunities and self.auto_better.enabled:
            for opp in opportunities:
                success, msg = await self.auto_better.place_polymarket_bet(opp)
                bk_instruction = self.auto_better.get_bk_instruction(opp)
                await self.telegram.send_bet_confirmation(
                    opp, poly_success=success, bk_note=bk_instruction
                )

        logger.info(f"Scan cycle complete. Found {len(opportunities)} opportunities.")

    async def run(self) -> None:
        """Run the scanner in a loop."""
        await self.initialize()
        self._running = True

        while self._running:
            try:
                await self.run_scan_cycle()
            except Exception as e:
                logger.exception(f"Scan cycle error: {e}")
                await self.telegram.send_error(f"Scan cycle error: {e}")

            logger.info(
                f"Next scan in {settings.scan_interval_seconds}s..."
            )
            await asyncio.sleep(settings.scan_interval_seconds)


def main() -> None:
    """Entry point."""
    scanner = ArbScanner()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(sig: int, _frame: object) -> None:
        logger.info(f"Received signal {sig}")
        loop.create_task(scanner.shutdown())

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(scanner.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        loop.run_until_complete(scanner.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
