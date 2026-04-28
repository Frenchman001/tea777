"""Arbitrage engine — core logic for finding and calculating arbitrage opportunities."""

from loguru import logger

from src.config import settings
from src.models.events import (
    ArbitrageOpportunity,
    BookmakerOdds,
    OutcomeType,
    PolymarketMarket,
)


def probability_to_decimal_odds(prob: float) -> float:
    """Convert a probability to decimal odds."""
    if prob <= 0:
        return 999.0
    return 1.0 / prob


def calculate_arbitrage(odds_a: float, odds_b: float) -> float | None:
    """Calculate arbitrage margin for two opposing outcomes.

    Returns profit percentage if arbitrage exists, None otherwise.
    Arbitrage exists when: 1/odds_a + 1/odds_b < 1
    """
    if odds_a < 1.01 or odds_b < 1.01:
        return None

    margin = (1.0 / odds_a) + (1.0 / odds_b)
    if margin < 1.0:
        profit_pct = ((1.0 / margin) - 1.0) * 100
        return profit_pct
    return None


def optimal_stakes(
    odds_a: float, odds_b: float, total_budget: float
) -> tuple[float, float, float]:
    """Calculate optimal stake distribution for guaranteed profit.

    Returns (stake_a, stake_b, guaranteed_profit).
    """
    if odds_a < 1.01 or odds_b < 1.01:
        return 0, 0, 0

    margin = (1.0 / odds_a) + (1.0 / odds_b)
    if margin >= 1.0:
        return 0, 0, 0

    stake_a = total_budget * (1.0 / odds_a) / margin
    stake_b = total_budget * (1.0 / odds_b) / margin

    payout_a = stake_a * odds_a
    payout_b = stake_b * odds_b
    guaranteed_payout = min(payout_a, payout_b)
    profit = guaranteed_payout - total_budget

    return stake_a, stake_b, profit


# Mapping of Polymarket YES/NO to bookmaker WIN_HOME/WIN_AWAY/DRAW
OUTCOME_PAIRS = [
    # Polymarket YES = BK team wins -> compare poly YES odds vs BK opposite
    (OutcomeType.YES, OutcomeType.WIN_AWAY),
    (OutcomeType.YES, OutcomeType.DRAW),
    (OutcomeType.NO, OutcomeType.WIN_HOME),
    (OutcomeType.NO, OutcomeType.WIN_AWAY),
    (OutcomeType.NO, OutcomeType.DRAW),
    # Direct matchups for multi-outcome poly markets
    (OutcomeType.WIN_HOME, OutcomeType.WIN_AWAY),
    (OutcomeType.WIN_HOME, OutcomeType.DRAW),
    (OutcomeType.WIN_AWAY, OutcomeType.WIN_HOME),
    (OutcomeType.WIN_AWAY, OutcomeType.DRAW),
]


class ArbitrageEngine:
    """Finds arbitrage opportunities between Polymarket and bookmakers."""

    def __init__(
        self,
        min_profit: float | None = None,
        max_stake: float | None = None,
    ) -> None:
        self.min_profit = min_profit or settings.min_profit_percent
        self.max_stake = max_stake or settings.max_stake_usd

    def find_opportunities(
        self,
        matched_pairs: list[tuple[PolymarketMarket, BookmakerOdds]],
    ) -> list[ArbitrageOpportunity]:
        """Scan all matched pairs for arbitrage opportunities."""
        opportunities: list[ArbitrageOpportunity] = []

        for market, bk_odds in matched_pairs:
            opps = self._check_pair(market, bk_odds)
            opportunities.extend(opps)

        opportunities.sort(key=lambda x: x.profit_percent, reverse=True)
        logger.info(
            f"Found {len(opportunities)} arbitrage opportunities "
            f"(min profit: {self.min_profit}%)"
        )
        return opportunities

    def _check_pair(
        self,
        market: PolymarketMarket,
        bk_odds: BookmakerOdds,
    ) -> list[ArbitrageOpportunity]:
        """Check a single market-BK pair for all possible arbitrage angles."""
        opportunities: list[ArbitrageOpportunity] = []

        for poly_side, bk_side in OUTCOME_PAIRS:
            poly_outcome = None
            for o in market.outcomes:
                if o.outcome_type == poly_side:
                    poly_outcome = o
                    break

            bk_outcome = bk_odds.get_outcome(bk_side)

            if not poly_outcome or not bk_outcome:
                continue

            poly_decimal = poly_outcome.odds
            bk_decimal = bk_outcome.odds

            profit_pct = calculate_arbitrage(poly_decimal, bk_decimal)
            if profit_pct is not None and profit_pct >= self.min_profit:
                stake_poly, stake_bk, profit = optimal_stakes(
                    poly_decimal, bk_decimal, self.max_stake
                )

                opp = ArbitrageOpportunity(
                    polymarket_market=market,
                    bookmaker_odds=bk_odds,
                    poly_side=poly_side,
                    bk_side=bk_side,
                    poly_odds=poly_decimal,
                    bk_odds=bk_decimal,
                    profit_percent=profit_pct,
                    optimal_poly_stake=round(stake_poly, 2),
                    optimal_bk_stake=round(stake_bk, 2),
                    total_stake=round(stake_poly + stake_bk, 2),
                    guaranteed_profit=round(profit, 2),
                )
                opportunities.append(opp)

                logger.info(
                    f"ARB FOUND: {market.question} | "
                    f"PM {poly_side.value}@{poly_decimal:.3f} vs "
                    f"{bk_odds.bookmaker} {bk_side.value}@{bk_decimal:.3f} | "
                    f"Profit: {profit_pct:.2f}%"
                )

        return opportunities
