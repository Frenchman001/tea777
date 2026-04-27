"""Exit Strategy — automated stop-loss, take-profit, and trailing stop rules.

Monitors positions and recommends exits based on configurable rules:
- Stop-loss: exit if price drops X% from entry
- Take-profit: lock in gains when price rises Y%
- Trailing stop: dynamic stop that follows price up
- Time-based: exit N hours before market resolution
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)


@dataclass
class ExitRule:
    rule_type: str  # STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, TIME_EXIT
    trigger_price: float
    current_price: float
    entry_price: float
    pnl_pct: float
    action: str
    urgency: str  # IMMEDIATE, SOON, WATCH

    @property
    def description(self) -> str:
        return (
            f"[{self.rule_type}] {self.action} | "
            f"Entry: {self.entry_price:.3f} → Now: {self.current_price:.3f} | "
            f"P&L: {self.pnl_pct:+.1f}% | Urgency: {self.urgency}"
        )


@dataclass
class Position:
    market_slug: str
    question: str
    side: str  # YES or NO
    entry_price: float
    size: float
    entry_time: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    highest_price: float = 0.0

    def __post_init__(self) -> None:
        if self.highest_price == 0:
            self.highest_price = self.entry_price


@dataclass
class ExitConfig:
    stop_loss_pct: float = 10.0
    take_profit_pct: float = 20.0
    trailing_stop_pct: float = 8.0
    time_exit_hours: float = 24.0
    max_hold_days: float = 30.0


class ExitStrategyEngine:
    """Monitors positions and generates exit signals."""

    def __init__(self, config: ExitConfig | None = None) -> None:
        self.config = config or ExitConfig()
        self.positions: list[Position] = []

    def add_position(self, position: Position) -> None:
        self.positions.append(position)

    def check_exits(self, markets: list[Market]) -> list[ExitRule]:
        """Check all positions against exit rules."""
        rules: list[ExitRule] = []
        market_map = {m.slug: m for m in markets}

        for pos in self.positions:
            market = market_map.get(pos.market_slug)
            if not market:
                continue

            current = market.yes_price if pos.side == "YES" else market.no_price
            pos_rules = self._evaluate_position(pos, market, current)
            rules.extend(pos_rules)

        rules.sort(key=lambda r: {"IMMEDIATE": 0, "SOON": 1, "WATCH": 2}[r.urgency])
        return rules

    def simulate_exits(
        self,
        markets: list[Market],
        entry_prices: dict[str, float] | None = None,
    ) -> list[ExitRule]:
        """Simulate exit rules for markets without actual positions.

        Assumes hypothetical entry at midpoint for demonstration.
        """
        rules: list[ExitRule] = []

        for market in markets:
            if not market.active or market.closed:
                continue

            yes = market.yes_price
            if yes <= 0.05 or yes >= 0.95:
                continue

            entry = entry_prices.get(market.slug, 0.5) if entry_prices else 0.5

            pos = Position(
                market_slug=market.slug,
                question=market.question,
                side="YES",
                entry_price=entry,
                size=100,
            )

            pos_rules = self._evaluate_position(pos, market, yes)
            rules.extend(pos_rules)

        rules.sort(key=lambda r: abs(r.pnl_pct), reverse=True)
        return rules[:20]

    def _evaluate_position(
        self,
        pos: Position,
        market: Market,
        current: float,
    ) -> list[ExitRule]:
        """Evaluate all exit rules for a position."""
        rules: list[ExitRule] = []

        if pos.entry_price <= 0:
            return rules

        pnl_pct = (current - pos.entry_price) / pos.entry_price * 100

        sl = self._check_stop_loss(pos, current, pnl_pct)
        if sl:
            rules.append(sl)

        tp = self._check_take_profit(pos, current, pnl_pct)
        if tp:
            rules.append(tp)

        ts = self._check_trailing_stop(pos, current)
        if ts:
            rules.append(ts)

        if pos.highest_price < current:
            pos.highest_price = current

        te = self._check_time_exit(pos, market)
        if te:
            rules.append(te)

        return rules

    def _check_stop_loss(
        self, pos: Position, current: float, pnl_pct: float,
    ) -> ExitRule | None:
        if pnl_pct <= -self.config.stop_loss_pct:
            return ExitRule(
                rule_type="STOP_LOSS",
                trigger_price=pos.entry_price * (1 - self.config.stop_loss_pct / 100),
                current_price=current,
                entry_price=pos.entry_price,
                pnl_pct=round(pnl_pct, 1),
                action=f"SELL {pos.side} on {pos.question[:30]}",
                urgency="IMMEDIATE",
            )
        return None

    def _check_take_profit(
        self, pos: Position, current: float, pnl_pct: float,
    ) -> ExitRule | None:
        if pnl_pct >= self.config.take_profit_pct:
            return ExitRule(
                rule_type="TAKE_PROFIT",
                trigger_price=pos.entry_price * (1 + self.config.take_profit_pct / 100),
                current_price=current,
                entry_price=pos.entry_price,
                pnl_pct=round(pnl_pct, 1),
                action=f"SELL {pos.side} on {pos.question[:30]} — LOCK PROFIT",
                urgency="SOON",
            )
        return None

    def _check_trailing_stop(
        self, pos: Position, current: float,
    ) -> ExitRule | None:
        if pos.highest_price <= pos.entry_price:
            return None

        drop_from_high = (pos.highest_price - current) / pos.highest_price * 100
        if drop_from_high >= self.config.trailing_stop_pct:
            pnl = (current - pos.entry_price) / pos.entry_price * 100
            return ExitRule(
                rule_type="TRAILING_STOP",
                trigger_price=pos.highest_price * (1 - self.config.trailing_stop_pct / 100),
                current_price=current,
                entry_price=pos.entry_price,
                pnl_pct=round(pnl, 1),
                action=f"SELL {pos.side} — dropped {drop_from_high:.0f}% from peak",
                urgency="IMMEDIATE",
            )
        return None

    def _check_time_exit(
        self, pos: Position, market: Market,
    ) -> ExitRule | None:
        if not market.end_date:
            return None

        try:
            raw = market.end_date.replace("Z", "+00:00")
            end_dt = datetime.fromisoformat(raw)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

        now = datetime.now(tz=timezone.utc)
        hours_left = (end_dt - now).total_seconds() / 3600

        if 0 < hours_left < self.config.time_exit_hours:
            current = pos.entry_price
            pnl = 0.0
            return ExitRule(
                rule_type="TIME_EXIT",
                trigger_price=current,
                current_price=current,
                entry_price=pos.entry_price,
                pnl_pct=pnl,
                action=f"EXIT {pos.side} — {hours_left:.0f}h to resolution",
                urgency="SOON",
            )
        return None
