"""CLI interface for Polymarket bot."""

from __future__ import annotations

import logging
import sys
import time

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from polymarket_bot.api_client import PolymarketClient
from polymarket_bot.arbitrage import ArbitrageScanner, MultiOutcomeArbitrageScanner
from polymarket_bot.config import Config
from polymarket_bot.correlations import CorrelationAnalyzer
from polymarket_bot.display import (
    display_alerts,
    display_arbitrage_opportunities,
    display_kelly,
    display_multi_outcome_arbitrage,
    display_signals,
    display_summary,
)
from polymarket_bot.profit_engine import (
    _guess_category,
    calculate_fee,
    estimate_slippage,
    kelly_criterion,
    score_market,
)
from polymarket_bot.signals import SignalAnalyzer
from polymarket_bot.smart_alerts import SmartAlertEngine

console = Console()

load_dotenv()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """Polymarket Arbitrage Scanner & Trading Signal Bot."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--min-profit", default=0.5, help="Min profit % to show")
@click.option("--min-volume", default=500.0, help="Min 24h volume USD")
@click.option("--use-orderbook", is_flag=True, help="Use CLOB orderbook for precise prices")
def arbitrage(max_markets: int, min_profit: float, min_volume: float, use_orderbook: bool) -> None:
    """Scan for arbitrage opportunities (YES + NO < 1.0)."""
    config = Config.from_env()
    config.min_profit_pct = min_profit
    config.min_volume_24h = min_volume
    config.max_markets_per_scan = max_markets

    console.print(Panel(
        f"[bold]Arbitrage Scanner[/bold]\n"
        f"Max markets: {max_markets} | Min profit: {min_profit}% | Min volume: ${min_volume:,.0f}\n"
        f"Mode: {'Orderbook (precise)' if use_orderbook else 'Gamma prices (fast)'}",
        border_style="green",
    ))

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching active markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        scanner = ArbitrageScanner(client, config)
        if use_orderbook:
            console.print("[dim]Checking orderbooks (this may take a while)...[/dim]")
            opps = scanner.scan_with_orderbook(markets)
        else:
            opps = scanner.scan(markets)

        display_arbitrage_opportunities(opps, title="Binary Market Arbitrage (YES + NO < 1.0)")

        console.print("\n[dim]Scanning multi-outcome events...[/dim]")
        multi_scanner = MultiOutcomeArbitrageScanner(client, config)
        multi_opps = multi_scanner.scan_events()
        display_multi_outcome_arbitrage(multi_opps)

        total_opps = len(opps) + len(multi_opps)
        if opps:
            best_pct = opps[0].profit_pct
        elif multi_opps:
            best_pct = multi_opps[0]["profit_pct"]
        else:
            best_pct = 0
        console.print(
            f"\n[bold green]Found {total_opps} arbitrage opportunities[/bold green]"
        )
        if best_pct > 0:
            console.print(f"[bold]Best opportunity: {best_pct:.2f}% guaranteed profit[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--min-confidence", default=0.6, help="Min confidence threshold")
@click.option("--top", default=20, help="Show top N signals")
def signals(max_markets: int, min_confidence: float, top: int) -> None:
    """Analyze markets and generate trading signals."""
    config = Config.from_env()
    config.min_confidence = min_confidence
    config.max_markets_per_scan = max_markets

    console.print(Panel(
        f"[bold]Signal Analyzer[/bold]\n"
        f"Max markets: {max_markets} | Min confidence: {min_confidence:.0%}",
        border_style="cyan",
    ))

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching active markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        analyzer = SignalAnalyzer(client, config)
        sigs = analyzer.analyze_markets(markets)
        display_signals(sigs[:top])

        console.print(f"\n[bold cyan]Generated {len(sigs)} signals[/bold cyan]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--min-profit", default=0.5, help="Min profit % for arbitrage")
@click.option("--min-confidence", default=0.6, help="Min confidence for signals")
@click.option("--min-volume", default=500.0, help="Min 24h volume USD")
def scan(max_markets: int, min_profit: float, min_confidence: float, min_volume: float) -> None:
    """Full scan: arbitrage + signals combined."""
    config = Config.from_env()
    config.min_profit_pct = min_profit
    config.min_confidence = min_confidence
    config.min_volume_24h = min_volume
    config.max_markets_per_scan = max_markets

    console.print(Panel(
        "[bold]Full Market Scan[/bold]\n"
        f"Markets: {max_markets} | Arb min: {min_profit}% | Signal min: {min_confidence:.0%}",
        border_style="blue",
    ))

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching active markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]\n")

        arb_scanner = ArbitrageScanner(client, config)
        arb_opps = arb_scanner.scan(markets)
        display_arbitrage_opportunities(arb_opps)

        multi_scanner = MultiOutcomeArbitrageScanner(client, config)
        multi_opps = multi_scanner.scan_events()
        display_multi_outcome_arbitrage(multi_opps)

        analyzer = SignalAnalyzer(client, config)
        sigs = analyzer.analyze_markets(markets)
        display_signals(sigs[:20])

        best_arb = arb_opps[0].profit_pct if arb_opps else 0
        best_sig = sigs[0].confidence if sigs else 0
        display_summary(
            len(markets), len(arb_opps) + len(multi_opps),
            len(sigs), best_arb, best_sig,
        )


@main.command()
@click.option("--interval", "-i", default=60, help="Scan interval in seconds")
@click.option("--max-markets", "-n", default=200, help="Max markets per scan")
@click.option("--min-profit", default=0.5, help="Min profit % for alerts")
def monitor(interval: int, max_markets: int, min_profit: float) -> None:
    """Continuously monitor markets for opportunities."""
    config = Config.from_env()
    config.min_profit_pct = min_profit
    config.max_markets_per_scan = max_markets
    config.scan_interval_sec = interval

    console.print(Panel(
        f"[bold]Live Monitor[/bold]\n"
        f"Interval: {interval}s | Markets: {max_markets} | Min profit: {min_profit}%\n"
        f"Press Ctrl+C to stop",
        border_style="magenta",
    ))

    scan_count = 0
    with PolymarketClient(config) as client:
        arb_scanner = ArbitrageScanner(client, config)
        analyzer = SignalAnalyzer(client, config)

        while True:
            try:
                scan_count += 1
                timestamp = time.strftime("%H:%M:%S")
                console.print(f"\n[dim]── Scan #{scan_count} at {timestamp} ──[/dim]")

                markets = client.get_all_active_markets(max_markets)
                arb_opps = arb_scanner.scan(markets)
                sigs = analyzer.analyze_markets(markets)

                if arb_opps:
                    title = f"Top Arbitrage (scan #{scan_count})"
                    display_arbitrage_opportunities(arb_opps[:5], title=title)
                if sigs:
                    title = f"Top Signals (scan #{scan_count})"
                    display_signals(sigs[:5], title=title)

                if not arb_opps and not sigs:
                    console.print("[dim]No opportunities found this scan[/dim]")

                console.print(f"[dim]Next scan in {interval}s...[/dim]")
                time.sleep(interval)

            except KeyboardInterrupt:
                console.print("\n[yellow]Monitor stopped[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                time.sleep(interval)


@main.command()
@click.argument("slug")
def market(slug: str) -> None:
    """Get detailed info about a specific market by slug."""
    config = Config.from_env()

    with PolymarketClient(config) as client:
        resp = client._http.get(
            f"{config.gamma_host}/markets", params={"slug": slug}
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            console.print(f"[red]Market not found: {slug}[/red]")
            return

        market_data = data[0] if isinstance(data, list) else data
        m = client._parse_market(market_data)

        console.print(Panel(f"[bold]{m.question}[/bold]", border_style="cyan"))
        console.print(f"  Condition ID: {m.condition_id}")
        console.print(f"  Slug: {m.slug}")
        console.print(f"  Active: {m.active} | Closed: {m.closed}")
        console.print(f"  Volume: ${m.volume:,.0f} | 24h: ${m.volume_24h:,.0f}")
        console.print(f"  Liquidity: ${m.liquidity:,.0f}")
        console.print(f"  End date: {m.end_date}")
        console.print(f"  Tags: {', '.join(m.tags)}")

        console.print("\n[bold]Tokens:[/bold]")
        for t in m.tokens:
            console.print(f"  {t.outcome}: {t.price:.4f} (ID: {t.token_id[:20]}...)")

        console.print(f"\n  Price sum: {m.price_sum:.4f}")
        console.print(f"  Spread from 1.0: {m.spread:.4f}")

        if m.yes_token_id:
            console.print("\n[bold]Orderbook (YES):[/bold]")
            try:
                book = client.get_order_book(m.yes_token_id)
                console.print(f"  Best bid: {book.best_bid:.4f}")
                console.print(f"  Best ask: {book.best_ask:.4f}")
                console.print(f"  Spread: {book.spread:.4f}")
                console.print(f"  Midpoint: {book.midpoint:.4f}")
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")


@main.command()
@click.option("--max-markets", "-n", default=300, help="Max markets to scan")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll in USD")
@click.option("--top", default=20, help="Show top N alerts")
def profit(max_markets: int, bankroll: float, top: int) -> None:
    """Maximum profit scan — smart alerts ranked by expected profit."""
    if bankroll <= 0:
        console.print("[red]Bankroll must be positive[/red]")
        return
    config = Config.from_env()
    config.max_markets_per_scan = max_markets
    config.min_profit_pct = 0.05
    config.min_volume_24h = 0
    config.min_confidence = 0.3

    console.print(Panel(
        f"[bold]PROFIT MAXIMIZER[/bold]\n"
        f"Bankroll: ${bankroll:,.0f} | Markets: {max_markets}\n"
        f"Kelly + Fees + Correlations + Scoring",
        border_style="bold green",
    ))

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        engine = SmartAlertEngine(client, config)
        summary = engine.generate_alerts(markets, bankroll=bankroll)

        display_alerts(summary.alerts[:top], title="Profit Opportunities")

        stats = summary.scan_stats
        console.print(Panel(
            f"[bold]Profit Summary[/bold]\n"
            f"Total alerts: {stats.get('total_alerts', 0)}\n"
            f"  Arbitrage: {stats.get('arbitrage_alerts', 0)}\n"
            f"  Signals: {stats.get('signal_alerts', 0)}\n"
            f"  Correlations: {stats.get('correlation_alerts', 0)}\n"
            f"  Top scores: {stats.get('score_alerts', 0)}\n"
            f"Expected total profit: "
            f"[green]${summary.total_expected_profit:.2f}[/green]",
            border_style="green",
        ))

        if summary.best_opportunity:
            best = summary.best_opportunity
            console.print(Panel(
                f"[bold]Best Opportunity[/bold]\n"
                f"{best.market_question[:70]}\n"
                f"Type: {best.alert_type} | "
                f"Profit: [green]${best.expected_profit_usd:.2f}[/green]\n"
                f"Bet: ${best.recommended_bet_usd:.0f} | "
                f"Confidence: {best.confidence:.0%} | "
                f"Risk: {best.risk_level}",
                border_style="bold yellow",
            ))


@main.command()
@click.argument("slug")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
@click.option("--probability", "-p", default=None, type=float,
              help="Your estimated true probability (0-1)")
def analyze(slug: str, bankroll: float, probability: float | None) -> None:
    """Deep analysis of a specific market with bet sizing."""
    if probability is not None and not (0.0 < probability < 1.0):
        console.print("[red]Probability must be between 0 and 1 (exclusive)[/red]")
        return
    if bankroll <= 0:
        console.print("[red]Bankroll must be positive[/red]")
        return
    config = Config.from_env()

    with PolymarketClient(config) as client:
        resp = client._http.get(
            f"{config.gamma_host}/markets", params={"slug": slug}
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            console.print(f"[red]Market not found: {slug}[/red]")
            return

        market_data = data[0] if isinstance(data, list) else data
        m = client._parse_market(market_data)

        console.print(Panel(f"[bold]{m.question}[/bold]", border_style="cyan"))

        # Basic info
        console.print(f"  YES: {m.yes_price:.4f} | NO: {m.no_price:.4f}")
        console.print(f"  Sum: {m.price_sum:.4f} | Spread: {m.spread:.4f}")
        console.print(f"  Volume 24h: ${m.volume_24h:,.0f}")
        console.print(f"  Liquidity: ${m.liquidity:,.0f}")

        # Fee calculation
        cat = _guess_category(m)
        fee_yes = calculate_fee(m.yes_price, 100, cat)
        console.print(f"\n[bold]Fees ({cat}):[/bold]")
        console.print(
            f"  100 shares YES: ${fee_yes.fee_amount:.4f}"
            f" ({fee_yes.effective_fee_pct:.3f}%)"
        )

        # Market score
        score = score_market(m, probability, bankroll)
        console.print(f"\n[bold]Score: {score.total_score:.1f}/10[/bold]")
        console.print(
            f"  EV={score.ev_score:.1f} Liq={score.liquidity_score:.1f}"
            f" Time={score.time_score:.1f} Vol={score.volume_score:.1f}"
        )
        console.print(f"  Risk: {score.risk_tier.value}")
        console.print(
            f"  Fee-adjusted EV: {score.fee_adjusted_ev:+.2%}"
        )
        for r in score.reasoning:
            console.print(f"    {r}")

        # Kelly sizing
        est_prob = probability or m.yes_price
        kelly_yes = kelly_criterion(
            est_prob, m.yes_price, bankroll, category=cat,
        )
        kelly_no = kelly_criterion(
            1.0 - est_prob, m.no_price, bankroll, category=cat,
        )

        best_kelly = kelly_yes if kelly_yes.edge > kelly_no.edge else kelly_no
        side = "YES" if kelly_yes.edge > kelly_no.edge else "NO"

        console.print(f"\n[bold]Recommended: {side}[/bold]")
        display_kelly(best_kelly)

        # Orderbook analysis
        token_id = m.yes_token_id if side == "YES" else m.no_token_id
        if token_id:
            try:
                book = client.get_order_book(token_id)
                slip = estimate_slippage(book, best_kelly.recommended_bet_usd)
                console.print(f"\n[bold]Orderbook ({side}):[/bold]")
                console.print(f"  Best ask: {book.best_ask:.4f}")
                console.print(f"  Best bid: {book.best_bid:.4f}")
                console.print(f"  Slippage: {slip.slippage_pct:.2f}%")
                console.print(
                    f"  Avg fill: {slip.avg_fill_price:.4f}"
                    f" ({slip.levels_consumed} levels)"
                )
            except Exception as e:
                console.print(f"  [red]Orderbook error: {e}[/red]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets")
def correlations(max_markets: int) -> None:
    """Find cross-market price divergences."""
    config = Config.from_env()

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        analyzer = CorrelationAnalyzer()
        pairs = analyzer.find_correlations(markets)

        if not pairs:
            console.print("[yellow]No price divergences found[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Cross-Market Divergences", show_lines=True)
        table.add_column("Type", style="bold")
        table.add_column("Market A", style="cyan", max_width=30)
        table.add_column("Market B", style="cyan", max_width=30)
        table.add_column("Divergence", justify="right", style="green")
        table.add_column("Profit Opp.", justify="right")

        for pair in pairs[:15]:
            q_a = pair.market_a.question[:30]
            q_b = pair.market_b.question[:30]
            table.add_row(
                pair.correlation_type,
                q_a,
                q_b,
                f"{pair.price_divergence:.1%}",
                f"{pair.profit_opportunity:.1%}",
            )

        console.print(table)

        console.print("\n[bold]Reasoning:[/bold]")
        for pair in pairs[:5]:
            console.print(f"  {pair.reasoning}")

        clusters = analyzer.find_event_clusters(markets)
        if clusters:
            console.print("\n[bold]Event Clusters:[/bold]")
            for c in clusters[:5]:
                console.print(
                    f"  {c.theme}: {len(c.markets)} markets"
                )


if __name__ == "__main__":
    main()
