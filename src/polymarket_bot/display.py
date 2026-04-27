"""Rich display helpers for CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from polymarket_bot.models import (
    ArbitrageOpportunity,
    SignalStrength,
    SignalType,
    TradingSignal,
)
from polymarket_bot.profit_engine import BetSizing

console = Console()


def display_arbitrage_opportunities(
    opps: list[ArbitrageOpportunity], title: str = "Arbitrage",
) -> None:
    if not opps:
        console.print(Panel("[yellow]No arbitrage opportunities found[/yellow]", title=title))
        return

    table = Table(title=title, show_lines=True)
    table.add_column("Market", style="cyan", max_width=50)
    table.add_column("YES", justify="right", style="green")
    table.add_column("NO", justify="right", style="red")
    table.add_column("Sum", justify="right")
    table.add_column("Profit %", justify="right", style="bold green")
    table.add_column("Liquidity", justify="right")
    table.add_column("Vol 24h", justify="right")

    for opp in opps:
        question = opp.market.question
        if len(question) > 50:
            question = question[:47] + "..."

        table.add_row(
            question,
            f"{opp.buy_yes_price:.3f}",
            f"{opp.buy_no_price:.3f}",
            f"{opp.price_sum:.3f}",
            f"{opp.profit_pct:.2f}%",
            f"{opp.liquidity_score:.2f}",
            f"${opp.market.volume_24h:,.0f}",
        )

    console.print(table)


def display_multi_outcome_arbitrage(
    opps: list[dict], title: str = "Multi-Outcome Arbitrage",
) -> None:
    if not opps:
        console.print(Panel("[yellow]No multi-outcome arbitrage found[/yellow]", title=title))
        return

    table = Table(title=title, show_lines=True)
    table.add_column("Event", style="cyan", max_width=45)
    table.add_column("Outcomes", justify="right")
    table.add_column("Total Price", justify="right")
    table.add_column("Profit %", justify="right", style="bold green")
    table.add_column("Days Left", justify="right")

    for opp in opps:
        title_text = opp["event_title"]
        if len(title_text) > 45:
            title_text = title_text[:42] + "..."
        days = str(opp["remaining_days"]) if opp["remaining_days"] is not None else "N/A"

        table.add_row(
            title_text,
            str(opp["num_outcomes"]),
            f"{opp['total_price']:.3f}",
            f"{opp['profit_pct']:.2f}%",
            days,
        )

    console.print(table)

    for opp in opps[:3]:
        console.print(f"\n[bold]{opp['event_title']}[/bold]")
        for m in opp["markets"]:
            console.print(f"  • {m['question'][:60]}: YES = {m['yes_price']:.3f}")


def display_signals(signals: list[TradingSignal], title: str = "Trading Signals") -> None:
    if not signals:
        console.print(Panel("[yellow]No trading signals found[/yellow]", title=title))
        return

    table = Table(title=title, show_lines=True)
    table.add_column("Type", style="bold")
    table.add_column("Market", style="cyan", max_width=40)
    table.add_column("Side", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("EV", justify="right")
    table.add_column("Strength", justify="center")
    table.add_column("Risk", justify="right")

    for sig in signals:
        type_color = _signal_type_color(sig.signal_type)
        strength_color = _strength_color(sig.strength)
        side_color = "green" if sig.recommended_side == "YES" else "red"

        question = sig.market.question
        if len(question) > 40:
            question = question[:37] + "..."

        table.add_row(
            f"[{type_color}]{sig.signal_type.value}[/{type_color}]",
            question,
            f"[{side_color}]{sig.recommended_side}[/{side_color}]",
            f"{sig.recommended_price:.3f}",
            f"{sig.confidence:.0%}",
            f"{sig.expected_value:+.3f}",
            f"[{strength_color}]{sig.strength.value}[/{strength_color}]",
            f"{sig.risk_score:.1f}",
        )

    console.print(table)

    console.print("\n[bold]Signal Details:[/bold]")
    for sig in signals[:5]:
        console.print(f"  [{_signal_type_color(sig.signal_type)}]●[/] {sig.reason}")


def display_market_details(market_data: dict) -> None:
    table = Table(title="Market Details", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    for key, value in market_data.items():
        table.add_row(str(key), str(value))

    console.print(table)


def display_summary(
    num_markets: int,
    arb_count: int,
    signal_count: int,
    best_arb_pct: float,
    best_signal_confidence: float,
) -> None:
    summary = Panel(
        f"[bold]Scan Summary[/bold]\n"
        f"Markets scanned: {num_markets}\n"
        f"Arbitrage opportunities: [green]{arb_count}[/green]\n"
        f"Trading signals: [cyan]{signal_count}[/cyan]\n"
        f"Best arbitrage: [green]{best_arb_pct:.2f}%[/green]\n"
        f"Highest confidence: [cyan]{best_signal_confidence:.0%}[/cyan]",
        title="Summary",
        border_style="blue",
    )
    console.print(summary)


def display_alerts(alerts: list, title: str = "Smart Alerts") -> None:
    """Display prioritized smart alerts."""
    if not alerts:
        console.print(Panel("[yellow]No alerts[/yellow]", title=title))
        return

    table = Table(title=title, show_lines=True)
    table.add_column("Priority", justify="center", style="bold")
    table.add_column("Type", style="bold")
    table.add_column("Market", style="cyan", max_width=35)
    table.add_column("Profit $", justify="right", style="green")
    table.add_column("Bet $", justify="right")
    table.add_column("Conf.", justify="right")
    table.add_column("Risk", justify="center")

    priority_colors = {
        "CRITICAL": "bold red",
        "HIGH": "bold yellow",
        "MEDIUM": "white",
        "LOW": "dim",
    }

    for alert in alerts:
        p_name = alert.priority.value if hasattr(alert.priority, "value") else str(alert.priority)
        p_color = priority_colors.get(p_name, "white")

        question = alert.market_question
        if len(question) > 35:
            question = question[:32] + "..."

        table.add_row(
            f"[{p_color}]{p_name}[/{p_color}]",
            alert.alert_type,
            question,
            f"${alert.expected_profit_usd:.2f}",
            f"${alert.recommended_bet_usd:.0f}",
            f"{alert.confidence:.0%}",
            alert.risk_level,
        )

    console.print(table)

    console.print("\n[bold]Details:[/bold]")
    for alert in alerts[:5]:
        p_name = alert.priority.value if hasattr(alert.priority, "value") else str(alert.priority)
        console.print(f"  [{priority_colors.get(p_name, 'white')}]{p_name}[/] {alert.details}")


def display_kelly(sizing: BetSizing) -> None:
    """Display Kelly Criterion bet sizing results."""
    console.print(Panel(
        f"[bold]Kelly Criterion Bet Sizing[/bold]\n"
        f"Win probability: {sizing.win_probability:.1%}\n"
        f"Edge: {sizing.edge:+.2%}\n"
        f"Kelly fraction: {sizing.kelly_fraction:.1%}\n"
        f"Full Kelly: ${sizing.kelly_bet_usd:.2f}\n"
        f"Half Kelly (recommended): "
        f"[green]${sizing.half_kelly_bet_usd:.2f}[/green]\n"
        f"Quarter Kelly: ${sizing.quarter_kelly_bet_usd:.2f}\n"
        f"Bankroll: ${sizing.bankroll:.2f}",
        border_style="green",
    ))


def _signal_type_color(st: SignalType) -> str:
    return {
        SignalType.ARBITRAGE: "green",
        SignalType.UNDERVALUED: "cyan",
        SignalType.OVERVALUED: "yellow",
        SignalType.MOMENTUM: "magenta",
    }.get(st, "white")


def _strength_color(s: SignalStrength) -> str:
    return {
        SignalStrength.STRONG: "bold green",
        SignalStrength.MEDIUM: "yellow",
        SignalStrength.WEAK: "dim",
    }.get(s, "white")
