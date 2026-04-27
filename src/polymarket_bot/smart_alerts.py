"""Smart alert system — prioritizes opportunities by expected profit.

Combines arbitrage, signals, correlations, and market scoring into
a single ranked feed of actionable opportunities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.arbitrage import ArbitrageScanner, MultiOutcomeArbitrageScanner
from polymarket_bot.config import Config
from polymarket_bot.correlations import CorrelationAnalyzer
from polymarket_bot.models import Market
from polymarket_bot.profit_engine import (
    kelly_criterion,
    score_market,
)
from polymarket_bot.signals import SignalAnalyzer


class AlertPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Alert:
    priority: AlertPriority
    alert_type: str
    title: str
    market_question: str
    expected_profit_usd: float
    recommended_bet_usd: float
    confidence: float
    details: str
    risk_level: str = "MEDIUM"
    market_slug: str = ""
    fee_impact_pct: float = 0.0

    @property
    def sort_key(self) -> float:
        priority_weights = {
            AlertPriority.CRITICAL: 1000,
            AlertPriority.HIGH: 100,
            AlertPriority.MEDIUM: 10,
            AlertPriority.LOW: 1,
        }
        return priority_weights[self.priority] + self.expected_profit_usd


@dataclass
class AlertSummary:
    alerts: list[Alert] = field(default_factory=list)
    total_expected_profit: float = 0.0
    best_opportunity: Alert | None = None
    scan_stats: dict[str, int] = field(default_factory=dict)


class SmartAlertEngine:
    """Generates prioritized alerts from all analysis sources."""

    def __init__(
        self, client: PolymarketClient, config: Config | None = None,
    ) -> None:
        self.client = client
        self.config = config or Config()
        self.arb_scanner = ArbitrageScanner(client, config)
        self.multi_arb_scanner = MultiOutcomeArbitrageScanner(client, config)
        self.signal_analyzer = SignalAnalyzer(client, config)
        self.correlation_analyzer = CorrelationAnalyzer()

    def generate_alerts(
        self,
        markets: list[Market] | None = None,
        bankroll: float = 1000.0,
    ) -> AlertSummary:
        if markets is None:
            markets = self.client.get_all_active_markets()

        alerts: list[Alert] = []

        arb_alerts = self._process_arbitrage(markets, bankroll)
        alerts.extend(arb_alerts)

        signal_alerts = self._process_signals(markets, bankroll)
        alerts.extend(signal_alerts)

        corr_alerts = self._process_correlations(markets, bankroll)
        alerts.extend(corr_alerts)

        score_alerts = self._process_top_scores(markets, bankroll)
        alerts.extend(score_alerts)

        seen_slugs: set[str] = set()
        unique: list[Alert] = []
        for a in alerts:
            key = f"{a.alert_type}:{a.market_slug}"
            if key not in seen_slugs:
                seen_slugs.add(key)
                unique.append(a)

        unique.sort(key=lambda a: a.sort_key, reverse=True)

        total_profit = sum(a.expected_profit_usd for a in unique)
        best = unique[0] if unique else None

        return AlertSummary(
            alerts=unique,
            total_expected_profit=round(total_profit, 2),
            best_opportunity=best,
            scan_stats={
                "markets_scanned": len(markets),
                "arbitrage_alerts": len(arb_alerts),
                "signal_alerts": len(signal_alerts),
                "correlation_alerts": len(corr_alerts),
                "score_alerts": len(score_alerts),
                "total_alerts": len(unique),
            },
        )

    def _process_arbitrage(
        self, markets: list[Market], bankroll: float,
    ) -> list[Alert]:
        alerts: list[Alert] = []

        opps = self.arb_scanner.scan(markets)
        for opp in opps:
            profit = opp.guaranteed_profit * min(bankroll * 0.1, 100)
            alerts.append(Alert(
                priority=AlertPriority.CRITICAL,
                alert_type="ARBITRAGE",
                title=f"Guaranteed {opp.profit_pct:.1f}% profit",
                market_question=opp.market.question,
                expected_profit_usd=round(profit, 2),
                recommended_bet_usd=round(min(bankroll * 0.1, 100), 2),
                confidence=0.99,
                details=(
                    f"Buy YES @ {opp.buy_yes_price:.3f} + "
                    f"NO @ {opp.buy_no_price:.3f} = {opp.price_sum:.3f}"
                ),
                risk_level="ULTRA_LOW",
                market_slug=opp.market.slug,
            ))

        multi_opps = self.multi_arb_scanner.scan_events()
        for mopp in multi_opps[:10]:
            profit = mopp["profit_pct"] / 100 * min(bankroll * 0.05, 50)
            alerts.append(Alert(
                priority=(
                    AlertPriority.CRITICAL
                    if mopp["profit_pct"] > 5
                    else AlertPriority.HIGH
                ),
                alert_type="MULTI_ARB",
                title=f"Multi-outcome arb: {mopp['profit_pct']:.1f}%",
                market_question=mopp["event_title"],
                expected_profit_usd=round(profit, 2),
                recommended_bet_usd=round(min(bankroll * 0.05, 50), 2),
                confidence=0.95,
                details=(
                    f"{mopp['num_outcomes']} outcomes, "
                    f"total price {mopp['total_price']:.3f}"
                ),
                risk_level="LOW",
                market_slug=mopp.get("event_slug", ""),
            ))

        return alerts

    def _process_signals(
        self, markets: list[Market], bankroll: float,
    ) -> list[Alert]:
        alerts: list[Alert] = []

        signals = self.signal_analyzer.analyze_markets(markets)
        for sig in signals[:20]:
            # Use signal's expected value to estimate true win probability.
            # confidence != win probability; derive from price + EV edge.
            est_prob = min(
                sig.recommended_price + sig.expected_value,
                0.95,
            )
            if est_prob <= sig.recommended_price:
                est_prob = sig.recommended_price + 0.01

            kelly = kelly_criterion(
                est_prob,
                sig.recommended_price,
                bankroll=bankroll,
            )

            expected_profit = kelly.recommended_bet_usd * kelly.edge

            if sig.confidence >= 0.8:
                priority = AlertPriority.HIGH
            elif sig.confidence >= 0.65:
                priority = AlertPriority.MEDIUM
            else:
                priority = AlertPriority.LOW

            alerts.append(Alert(
                priority=priority,
                alert_type=sig.signal_type.value,
                title=f"{sig.signal_type.value}: {sig.strength.value}",
                market_question=sig.market.question,
                expected_profit_usd=round(max(expected_profit, 0), 2),
                recommended_bet_usd=kelly.recommended_bet_usd,
                confidence=sig.confidence,
                details=sig.reason,
                risk_level=_risk_from_score(sig.risk_score),
                market_slug=sig.market.slug,
            ))

        return alerts

    def _process_correlations(
        self, markets: list[Market], bankroll: float,
    ) -> list[Alert]:
        alerts: list[Alert] = []

        pairs = self.correlation_analyzer.find_correlations(markets)
        for pair in pairs[:10]:
            profit = pair.profit_opportunity * min(bankroll * 0.03, 30)
            alerts.append(Alert(
                priority=(
                    AlertPriority.HIGH
                    if pair.price_divergence > 0.1
                    else AlertPriority.MEDIUM
                ),
                alert_type=f"CORR_{pair.correlation_type}",
                title=f"Price divergence: {pair.price_divergence:.1%}",
                market_question=(
                    f"{pair.market_a.question[:40]} ↔ "
                    f"{pair.market_b.question[:40]}"
                ),
                expected_profit_usd=round(profit, 2),
                recommended_bet_usd=round(min(bankroll * 0.03, 30), 2),
                confidence=0.7,
                details=pair.reasoning,
                risk_level="MEDIUM",
                market_slug=f"{pair.market_a.slug}|{pair.market_b.slug}",
            ))

        return alerts

    def _process_top_scores(
        self, markets: list[Market], bankroll: float,
    ) -> list[Alert]:
        alerts: list[Alert] = []

        scored = [score_market(m, bankroll=bankroll) for m in markets]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        for ms in scored[:5]:
            if ms.total_score < 3.0 or ms.fee_adjusted_ev <= 0:
                continue

            alerts.append(Alert(
                priority=(
                    AlertPriority.HIGH
                    if ms.total_score >= 6
                    else AlertPriority.MEDIUM
                ),
                alert_type="TOP_SCORE",
                title=f"Score {ms.total_score:.1f}/10",
                market_question=ms.market.question,
                expected_profit_usd=ms.expected_profit_usd,
                recommended_bet_usd=ms.recommended_bet,
                confidence=min(ms.fee_adjusted_ev * 5 + 0.5, 0.95),
                details=(
                    f"EV={ms.ev_score:.1f} Liq={ms.liquidity_score:.1f} "
                    f"Time={ms.time_score:.1f} Vol={ms.volume_score:.1f} | "
                    + "; ".join(ms.reasoning[:2])
                ),
                risk_level=ms.risk_tier.value,
                market_slug=ms.market.slug,
                fee_impact_pct=ms.fee_adjusted_ev * 100,
            ))

        return alerts


def _risk_from_score(score: float) -> str:
    if score <= 0.3:
        return "LOW"
    if score <= 0.6:
        return "MEDIUM"
    return "HIGH"
