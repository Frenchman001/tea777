"""Portfolio optimization — manages risk allocation across correlated bets.

Prevents over-concentration in a single theme and tracks bankroll usage.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from polymarket_bot.smart_alerts import Alert

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path.home() / ".polymarket_bot" / "portfolio.json"


@dataclass
class Position:
    market_slug: str
    side: str
    entry_price: float
    size_usd: float
    category: str
    theme: str = ""

    @property
    def current_exposure(self) -> float:
        return self.size_usd


@dataclass
class PortfolioLimits:
    max_single_bet_pct: float = 0.10
    max_theme_pct: float = 0.25
    max_category_pct: float = 0.35
    max_correlated_pct: float = 0.30
    max_total_invested_pct: float = 0.80
    min_cash_reserve_pct: float = 0.20


@dataclass
class AllocationResult:
    approved: bool
    adjusted_bet_usd: float
    original_bet_usd: float
    reason: str
    theme_exposure_pct: float
    category_exposure_pct: float
    total_invested_pct: float


class PortfolioManager:
    """Manages portfolio allocation and risk limits."""

    def __init__(
        self,
        bankroll: float = 1000.0,
        limits: PortfolioLimits | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.bankroll = bankroll
        self.limits = limits or PortfolioLimits()
        self.positions: list[Position] = []
        self._state_path = state_path or DEFAULT_STATE_PATH

    @property
    def total_invested(self) -> float:
        return sum(p.size_usd for p in self.positions)

    @property
    def cash_available(self) -> float:
        return max(self.bankroll - self.total_invested, 0)

    @property
    def invested_pct(self) -> float:
        return self.total_invested / self.bankroll if self.bankroll > 0 else 0

    def theme_exposure(self, theme: str) -> float:
        """Total USD invested in a given theme."""
        return sum(p.size_usd for p in self.positions if p.theme == theme)

    def category_exposure(self, category: str) -> float:
        """Total USD invested in a given category."""
        return sum(p.size_usd for p in self.positions if p.category == category)

    def check_allocation(
        self,
        alert: Alert,
        category: str = "other",
        theme: str = "",
    ) -> AllocationResult:
        """Check if a new bet fits within portfolio limits."""
        bet = alert.recommended_bet_usd
        orig_bet = bet

        max_single = self.bankroll * self.limits.max_single_bet_pct
        if bet > max_single:
            bet = max_single

        max_total = self.bankroll * self.limits.max_total_invested_pct
        remaining_capacity = max_total - self.total_invested
        if remaining_capacity <= 0:
            return AllocationResult(
                approved=False, adjusted_bet_usd=0, original_bet_usd=orig_bet,
                reason=(
                    f"Portfolio {self.invested_pct:.0%} invested "
                    f"(max {self.limits.max_total_invested_pct:.0%})"
                ),
                theme_exposure_pct=0, category_exposure_pct=0,
                total_invested_pct=self.invested_pct,
            )
        bet = min(bet, remaining_capacity)

        if theme:
            theme_total = self.theme_exposure(theme) + bet
            max_theme = self.bankroll * self.limits.max_theme_pct
            if theme_total > max_theme:
                bet = max(max_theme - self.theme_exposure(theme), 0)
                if bet <= 0:
                    return AllocationResult(
                        approved=False, adjusted_bet_usd=0, original_bet_usd=orig_bet,
                        reason=f"Theme '{theme}' at limit ({self.limits.max_theme_pct:.0%})",
                        theme_exposure_pct=self.theme_exposure(theme) / self.bankroll,
                        category_exposure_pct=self.category_exposure(category) / self.bankroll,
                        total_invested_pct=self.invested_pct,
                    )

        cat_total = self.category_exposure(category) + bet
        max_cat = self.bankroll * self.limits.max_category_pct
        if cat_total > max_cat:
            bet = max(max_cat - self.category_exposure(category), 0)
            if bet <= 0:
                return AllocationResult(
                    approved=False, adjusted_bet_usd=0, original_bet_usd=orig_bet,
                    reason=f"Category '{category}' at limit ({self.limits.max_category_pct:.0%})",
                    theme_exposure_pct=self.theme_exposure(theme) / self.bankroll if theme else 0,
                    category_exposure_pct=self.category_exposure(category) / self.bankroll,
                    total_invested_pct=self.invested_pct,
                )

        reason = "OK"
        if bet < orig_bet:
            reason = f"Reduced from ${orig_bet:.0f} to ${bet:.0f} (limits)"

        theme_pct = (self.theme_exposure(theme) + bet) / self.bankroll if theme else 0
        cat_pct = (self.category_exposure(category) + bet) / self.bankroll

        return AllocationResult(
            approved=bet > 0,
            adjusted_bet_usd=round(bet, 2),
            original_bet_usd=orig_bet,
            reason=reason,
            theme_exposure_pct=round(theme_pct, 3),
            category_exposure_pct=round(cat_pct, 3),
            total_invested_pct=round((self.total_invested + bet) / self.bankroll, 3),
        )

    def add_position(
        self,
        market_slug: str,
        side: str,
        entry_price: float,
        size_usd: float,
        category: str = "other",
        theme: str = "",
    ) -> Position:
        """Record a new position."""
        pos = Position(
            market_slug=market_slug,
            side=side,
            entry_price=entry_price,
            size_usd=size_usd,
            category=category,
            theme=theme,
        )
        self.positions.append(pos)
        return pos

    def remove_position(self, market_slug: str) -> bool:
        """Remove a position (market resolved or closed)."""
        before = len(self.positions)
        self.positions = [p for p in self.positions if p.market_slug != market_slug]
        return len(self.positions) < before

    def get_summary(self) -> dict:
        """Return portfolio summary."""
        by_category: dict[str, float] = defaultdict(float)
        by_theme: dict[str, float] = defaultdict(float)
        for p in self.positions:
            by_category[p.category] += p.size_usd
            if p.theme:
                by_theme[p.theme] += p.size_usd

        return {
            "bankroll": self.bankroll,
            "total_invested": round(self.total_invested, 2),
            "cash_available": round(self.cash_available, 2),
            "invested_pct": f"{self.invested_pct:.1%}",
            "num_positions": len(self.positions),
            "by_category": dict(by_category),
            "by_theme": dict(by_theme),
        }

    def save_state(self) -> None:
        """Persist portfolio state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "bankroll": self.bankroll,
            "positions": [
                {
                    "market_slug": p.market_slug,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "size_usd": p.size_usd,
                    "category": p.category,
                    "theme": p.theme,
                }
                for p in self.positions
            ],
        }
        self._state_path.write_text(json.dumps(data, indent=2))

    def load_state(self) -> bool:
        """Load portfolio state from disk. Returns True if loaded."""
        if not self._state_path.exists():
            return False
        try:
            data = json.loads(self._state_path.read_text())
            self.bankroll = data.get("bankroll", self.bankroll)
            self.positions = [
                Position(**p) for p in data.get("positions", [])
            ]
            return True
        except Exception as e:
            logger.warning("Failed to load portfolio state: %s", e)
            return False


def optimize_alerts(
    alerts: list[Alert],
    bankroll: float = 1000.0,
    limits: PortfolioLimits | None = None,
) -> list[tuple[Alert, AllocationResult]]:
    """Apply portfolio limits to a list of alerts, returning approved ones."""
    manager = PortfolioManager(bankroll=bankroll, limits=limits)
    results: list[tuple[Alert, AllocationResult]] = []

    for alert in alerts:
        category = "other"
        theme = ""

        if "MULTI_ARB" in alert.alert_type or "ARBITRAGE" in alert.alert_type:
            category = "arbitrage"
        elif "CORR_" in alert.alert_type:
            theme = alert.alert_type.replace("CORR_", "").lower()

        alloc = manager.check_allocation(alert, category=category, theme=theme)
        results.append((alert, alloc))

        if alloc.approved:
            manager.add_position(
                market_slug=alert.market_slug,
                side="YES",
                entry_price=0.5,
                size_usd=alloc.adjusted_bet_usd,
                category=category,
                theme=theme,
            )

    return results
