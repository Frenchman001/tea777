"""Backtesting engine — tests strategies on historical resolved markets.

Fetches resolved markets from Polymarket API and simulates trading
to calculate P&L, win rate, Sharpe ratio, and max drawdown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.config import Config
from polymarket_bot.models import Market
from polymarket_bot.profit_engine import calculate_fee, kelly_criterion

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    market_slug: str
    question: str
    side: str
    entry_price: float
    bet_usd: float
    won: bool
    pnl: float
    fee: float

    @property
    def net_pnl(self) -> float:
        return self.pnl - self.fee


@dataclass
class BacktestResult:
    strategy_name: str
    total_markets: int
    trades_taken: int
    wins: int
    losses: int
    total_pnl: float
    total_fees: float
    net_pnl: float
    win_rate: float
    avg_pnl_per_trade: float
    max_drawdown: float
    sharpe_ratio: float
    best_trade: BacktestTrade | None = None
    worst_trade: BacktestTrade | None = None
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def roi_pct(self) -> float:
        if not self.trades:
            return 0.0
        total_invested = sum(t.bet_usd for t in self.trades)
        return (self.net_pnl / total_invested * 100) if total_invested > 0 else 0.0


class BacktestEngine:
    """Runs strategy backtests on resolved Polymarket markets."""

    def __init__(
        self,
        client: PolymarketClient,
        config: Config | None = None,
        bankroll: float = 1000.0,
    ) -> None:
        self.client = client
        self.config = config or Config()
        self.bankroll = bankroll

    def fetch_resolved_markets(self, limit: int = 200) -> list[Market]:
        """Fetch recently resolved markets for backtesting."""
        markets = self.client.get_markets(
            limit=limit, active=False, closed=True,
            order="volume24hr", ascending=False,
        )
        resolved = [m for m in markets if self._is_resolved(m)]
        return resolved

    def _is_resolved(self, market: Market) -> bool:
        """Check if a market has resolved (has a winner)."""
        return any(t.winner for t in market.tokens)

    def _get_winner(self, market: Market) -> str:
        """Get the winning outcome."""
        for t in market.tokens:
            if t.winner:
                return t.outcome.upper()
        return ""

    def run_kelly_strategy(
        self,
        markets: list[Market],
        min_edge: float = 0.03,
        category: str = "other",
    ) -> BacktestResult:
        """Backtest the Kelly Criterion strategy."""
        trades: list[BacktestTrade] = []
        running_bankroll = self.bankroll
        peak_bankroll = self.bankroll
        max_dd = 0.0

        for market in markets:
            winner = self._get_winner(market)
            if not winner:
                continue

            yes_price = market.yes_price
            if yes_price <= 0.05 or yes_price >= 0.95:
                continue

            est_prob = yes_price + 0.03
            kelly = kelly_criterion(
                est_prob, yes_price,
                bankroll=running_bankroll,
                category=category,
            )

            if kelly.edge < min_edge or kelly.recommended_bet_usd <= 0:
                continue

            bet = min(kelly.recommended_bet_usd, running_bankroll * 0.1)
            fee_est = calculate_fee(yes_price, bet / yes_price, category)

            won = winner == "YES"
            if won:
                pnl = bet * (1.0 / yes_price - 1.0)
            else:
                pnl = -bet

            trade = BacktestTrade(
                market_slug=market.slug,
                question=market.question,
                side="YES",
                entry_price=yes_price,
                bet_usd=bet,
                won=won,
                pnl=round(pnl, 2),
                fee=round(fee_est.fee_amount, 2),
            )
            trades.append(trade)
            running_bankroll += trade.net_pnl

            if running_bankroll > peak_bankroll:
                peak_bankroll = running_bankroll
            dd = (peak_bankroll - running_bankroll) / peak_bankroll if peak_bankroll > 0 else 0
            max_dd = max(max_dd, dd)

        return self._compile_result("Kelly Criterion", trades, max_dd)

    def run_arbitrage_strategy(
        self, markets: list[Market],
    ) -> BacktestResult:
        """Backtest pure arbitrage strategy (buy YES+NO when sum < 1)."""
        trades: list[BacktestTrade] = []
        max_dd = 0.0

        for market in markets:
            price_sum = market.price_sum
            if price_sum >= 0.995 or price_sum <= 0.05:
                continue

            profit_pct = (1.0 - price_sum) * 100
            if profit_pct < 0.5:
                continue

            bet = min(50, self.bankroll * 0.05)
            pnl = bet * (1.0 - price_sum)

            trade = BacktestTrade(
                market_slug=market.slug,
                question=market.question,
                side="BOTH",
                entry_price=price_sum,
                bet_usd=bet,
                won=True,
                pnl=round(pnl, 2),
                fee=0.0,
            )
            trades.append(trade)

        return self._compile_result("Arbitrage", trades, max_dd)

    def run_value_strategy(
        self,
        markets: list[Market],
        threshold: float = 0.10,
    ) -> BacktestResult:
        """Backtest value strategy — buy underpriced outcomes."""
        trades: list[BacktestTrade] = []
        running_bankroll = self.bankroll
        peak_bankroll = self.bankroll
        max_dd = 0.0

        for market in markets:
            winner = self._get_winner(market)
            if not winner:
                continue

            yes_price = market.yes_price
            if yes_price <= 0 or yes_price >= 1:
                continue

            if yes_price < threshold:
                bet = min(20, running_bankroll * 0.02)
                won = winner == "YES"
                pnl = bet * (1.0 / yes_price - 1.0) if won else -bet

                trade = BacktestTrade(
                    market_slug=market.slug,
                    question=market.question,
                    side="YES",
                    entry_price=yes_price,
                    bet_usd=bet,
                    won=won,
                    pnl=round(pnl, 2),
                    fee=0.0,
                )
                trades.append(trade)
                running_bankroll += trade.net_pnl

                if running_bankroll > peak_bankroll:
                    peak_bankroll = running_bankroll
                dd = (peak_bankroll - running_bankroll) / peak_bankroll if peak_bankroll > 0 else 0
                max_dd = max(max_dd, dd)

            no_price = market.no_price
            if 0 < no_price < threshold:
                bet = min(20, running_bankroll * 0.02)
                won = winner == "NO"
                pnl = bet * (1.0 / no_price - 1.0) if won else -bet

                trade = BacktestTrade(
                    market_slug=market.slug,
                    question=market.question,
                    side="NO",
                    entry_price=no_price,
                    bet_usd=bet,
                    won=won,
                    pnl=round(pnl, 2),
                    fee=0.0,
                )
                trades.append(trade)
                running_bankroll += trade.net_pnl

                if running_bankroll > peak_bankroll:
                    peak_bankroll = running_bankroll
                dd = (peak_bankroll - running_bankroll) / peak_bankroll if peak_bankroll > 0 else 0
                max_dd = max(max_dd, dd)

        return self._compile_result("Value Betting", trades, max_dd)

    def _compile_result(
        self, name: str, trades: list[BacktestTrade], max_dd: float,
    ) -> BacktestResult:
        wins = [t for t in trades if t.won]
        losses = [t for t in trades if not t.won]
        total_pnl = sum(t.pnl for t in trades)
        total_fees = sum(t.fee for t in trades)
        net_pnl = total_pnl - total_fees

        pnls = [t.net_pnl for t in trades]
        avg_pnl = net_pnl / len(trades) if trades else 0
        sharpe = 0.0
        if len(pnls) >= 2:
            mean = sum(pnls) / len(pnls)
            variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
            std = variance ** 0.5
            sharpe = mean / std if std > 0 else 0.0

        best = max(trades, key=lambda t: t.net_pnl) if trades else None
        worst = min(trades, key=lambda t: t.net_pnl) if trades else None

        return BacktestResult(
            strategy_name=name,
            total_markets=len(trades),
            trades_taken=len(trades),
            wins=len(wins),
            losses=len(losses),
            total_pnl=round(total_pnl, 2),
            total_fees=round(total_fees, 2),
            net_pnl=round(net_pnl, 2),
            win_rate=len(wins) / len(trades) if trades else 0,
            avg_pnl_per_trade=round(avg_pnl, 2),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 3),
            best_trade=best,
            worst_trade=worst,
            trades=trades,
        )
