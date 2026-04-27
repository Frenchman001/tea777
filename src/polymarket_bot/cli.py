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
from polymarket_bot.display import (
    display_arbitrage_opportunities,
    display_multi_outcome_arbitrage,
    display_signals,
    display_summary,
)
from polymarket_bot.signals import SignalAnalyzer

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


if __name__ == "__main__":
    main()
