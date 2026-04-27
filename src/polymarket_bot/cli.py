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


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to check")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
@click.option("--notify/--no-notify", default=False, help="Send Telegram notifications")
def profit_plus(max_markets: int, bankroll: float, notify: bool) -> None:
    """Enhanced profit scan with liquidity checks, portfolio limits, and external data."""
    if bankroll <= 0:
        console.print("[red]Bankroll must be positive[/red]")
        return
    config = Config.from_env()
    config.max_markets_per_scan = max_markets
    config.min_profit_pct = 0.05
    config.min_volume_24h = 0
    config.min_confidence = 0.3

    from polymarket_bot.external_data import ExternalDataAggregator
    from polymarket_bot.portfolio import optimize_alerts

    console.print(Panel(
        f"[bold]PROFIT MAXIMIZER v2[/bold]\n"
        f"Bankroll: ${bankroll:,.0f} | Markets: {max_markets}\n"
        f"Kelly + Fees + Liquidity + Portfolio + External Data",
        border_style="bold green",
    ))

    with PolymarketClient(config) as client:
        console.print("[dim]Fetching markets...[/dim]")
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        engine = SmartAlertEngine(client, config)
        summary = engine.generate_alerts(markets, bankroll=bankroll)

        # Portfolio optimization
        console.print("[dim]Applying portfolio limits...[/dim]")
        optimized = optimize_alerts(summary.alerts, bankroll=bankroll)
        approved = [(a, r) for a, r in optimized if r.approved]

        # External data
        console.print("[dim]Checking external data sources...[/dim]")
        ext = ExternalDataAggregator()
        try:
            ext_signals = ext.analyze_markets(markets)
        finally:
            ext.close()

        # Display results
        from rich.table import Table

        if approved:
            table = Table(title="Approved Opportunities (Portfolio-Optimized)", show_lines=True)
            table.add_column("Type", style="bold")
            table.add_column("Market", style="cyan", max_width=40)
            table.add_column("Bet", justify="right", style="green")
            table.add_column("Profit", justify="right", style="bold green")
            table.add_column("Theme%", justify="right")
            table.add_column("Status")

            for alert, alloc in approved[:20]:
                q = alert.market_question[:40]
                table.add_row(
                    alert.alert_type,
                    q,
                    f"${alloc.adjusted_bet_usd:.0f}",
                    f"${alert.expected_profit_usd:.2f}",
                    f"{alloc.theme_exposure_pct:.0%}",
                    alloc.reason[:20],
                )
            console.print(table)

        if ext_signals:
            table = Table(title="External Data Signals", show_lines=True)
            table.add_column("Source", style="bold")
            table.add_column("Market", style="cyan", max_width=40)
            table.add_column("Poly Price", justify="right")
            table.add_column("Est. Prob", justify="right", style="green")
            table.add_column("Edge", justify="right", style="bold yellow")
            table.add_column("Side", justify="center")

            for sig in ext_signals[:10]:
                q = sig.market_question[:40]
                table.add_row(
                    sig.source,
                    q,
                    f"{sig.polymarket_price:.0%}",
                    f"{sig.estimated_probability:.0%}",
                    f"{sig.edge:+.1%}",
                    sig.recommended_side,
                )
            console.print(table)

        total_approved_profit = sum(a.expected_profit_usd for a, _ in approved)
        total_bet = sum(r.adjusted_bet_usd for _, r in approved)
        rejected = len(optimized) - len(approved)

        console.print(Panel(
            f"[bold]Summary[/bold]\n"
            f"Total alerts: {len(summary.alerts)} | Approved: {len(approved)} | "
            f"Rejected: {rejected}\n"
            f"Total bet: ${total_bet:.0f} / ${bankroll:.0f} bankroll\n"
            f"Expected profit: [green]${total_approved_profit:.2f}[/green]\n"
            f"External signals: {len(ext_signals)}",
            border_style="green",
        ))

        # Telegram notifications
        if notify:
            from polymarket_bot.telegram_alerts import TelegramNotifier
            tg = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
            if tg.is_configured:
                tg.send_summary(summary)
                tg.send_top_alerts(summary.alerts[:5])
                console.print("[green]Telegram notifications sent[/green]")
                tg.close()
            else:
                console.print(
                    "[yellow]Telegram not configured"
                    " (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)[/yellow]"
                )


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets to fetch")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
def backtest(max_markets: int, bankroll: float) -> None:
    """Backtest strategies on resolved markets."""
    if bankroll <= 0:
        console.print("[red]Bankroll must be positive[/red]")
        return
    config = Config.from_env()

    from polymarket_bot.backtesting import BacktestEngine

    console.print(Panel(
        f"[bold]Backtesting Engine[/bold]\n"
        f"Fetching {max_markets} resolved markets | Bankroll: ${bankroll:,.0f}",
        border_style="yellow",
    ))

    with PolymarketClient(config) as client:
        bt = BacktestEngine(client, config, bankroll=bankroll)

        console.print("[dim]Fetching resolved markets...[/dim]")
        resolved = bt.fetch_resolved_markets(max_markets)
        console.print(f"[dim]Found {len(resolved)} resolved markets[/dim]")

        if not resolved:
            console.print("[yellow]No resolved markets found for backtesting[/yellow]")
            return

        from rich.table import Table

        results = [
            bt.run_kelly_strategy(resolved),
            bt.run_arbitrage_strategy(resolved),
            bt.run_value_strategy(resolved),
        ]

        table = Table(title="Backtest Results", show_lines=True)
        table.add_column("Strategy", style="bold")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Net P&L", justify="right")
        table.add_column("ROI", justify="right")
        table.add_column("Sharpe", justify="right")
        table.add_column("Max DD", justify="right")

        for r in results:
            pnl_color = "green" if r.net_pnl >= 0 else "red"
            table.add_row(
                r.strategy_name,
                str(r.trades_taken),
                f"{r.win_rate:.0%}",
                f"[{pnl_color}]${r.net_pnl:.2f}[/{pnl_color}]",
                f"{r.roi_pct:.1f}%",
                f"{r.sharpe_ratio:.2f}",
                f"{r.max_drawdown:.1%}",
            )

        console.print(table)

        for r in results:
            if r.best_trade:
                console.print(
                    f"\n[bold]{r.strategy_name}[/bold] best: "
                    f"{r.best_trade.question[:50]}... "
                    f"[green]+${r.best_trade.net_pnl:.2f}[/green]"
                )


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets")
def ml_predict(max_markets: int) -> None:
    """ML-based market outcome predictions."""
    config = Config.from_env()

    from polymarket_bot.ml_predictor import MLPredictor

    console.print(Panel(
        "[bold]ML Predictor[/bold]\nLogistic regression on market features",
        border_style="magenta",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        predictor = MLPredictor()
        predictions = predictor.predict_markets(markets)

        if not predictions:
            console.print("[yellow]No high-edge predictions found[/yellow]")
            return

        from rich.table import Table
        table = Table(title="ML Predictions (|edge| > 5%)", show_lines=True)
        table.add_column("Market", style="cyan", max_width=45)
        table.add_column("Predicted", justify="right", style="green")
        table.add_column("Market $", justify="right")
        table.add_column("Edge", justify="right", style="bold yellow")
        table.add_column("Side", justify="center")

        for p in predictions[:15]:
            q = p.question[:45]
            table.add_row(
                q,
                f"{p.predicted_prob:.0%}",
                f"{p.market_price:.0%}",
                f"{p.edge:+.1%}",
                p.recommended_side,
            )
        console.print(table)
        console.print(f"\n[bold]Total predictions with edge: {len(predictions)}[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets")
def cross_arb(max_markets: int) -> None:
    """Find cross-platform and internal arbitrage opportunities."""
    config = Config.from_env()

    from polymarket_bot.cross_platform import CrossPlatformScanner

    console.print(Panel(
        "[bold]Cross-Platform Arbitrage[/bold]\nPolymarket vs Kalshi + internal dupes",
        border_style="blue",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        scanner = CrossPlatformScanner()
        try:
            console.print("[dim]Checking Kalshi markets...[/dim]")
            cross_arbs = scanner.find_cross_arb(markets)

            console.print("[dim]Checking internal duplicates...[/dim]")
            internal = scanner.find_internal_cross_arb(markets)
        finally:
            scanner.close()

        from rich.table import Table

        if internal:
            table = Table(title="Internal Arbitrage (Similar Markets)", show_lines=True)
            table.add_column("Market A", style="cyan", max_width=30)
            table.add_column("Price A", justify="right")
            table.add_column("Market B", style="cyan", max_width=30)
            table.add_column("Price B", justify="right")
            table.add_column("Diff", justify="right", style="bold green")

            for arb in internal[:10]:
                table.add_row(
                    arb.polymarket.question[:30],
                    f"{arb.poly_yes:.0%}",
                    arb.external.title[:30],
                    f"{arb.ext_yes:.0%}",
                    f"{arb.price_diff:.1%}",
                )
            console.print(table)

        if cross_arbs:
            table = Table(title="Cross-Platform Arbitrage", show_lines=True)
            table.add_column("Polymarket", style="cyan", max_width=30)
            table.add_column("Poly $", justify="right")
            table.add_column("Platform", style="bold")
            table.add_column("Ext $", justify="right")
            table.add_column("Diff", justify="right", style="bold green")

            for arb in cross_arbs[:10]:
                table.add_row(
                    arb.polymarket.question[:30],
                    f"{arb.poly_yes:.0%}",
                    arb.external.platform,
                    f"{arb.ext_yes:.0%}",
                    f"{arb.price_diff:.1%}",
                )
            console.print(table)
        else:
            console.print("[yellow]No cross-platform arbitrage found[/yellow]")

        total = len(cross_arbs) + len(internal)
        console.print(f"\n[bold]Found {total} opportunities[/bold] "
                      f"(cross: {len(cross_arbs)}, internal: {len(internal)})")


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets")
@click.option("--min-volume", default=10000.0, help="Min 24h volume for MM")
def mm_scan(max_markets: int, min_volume: float) -> None:
    """Scan for market making opportunities."""
    config = Config.from_env()

    from polymarket_bot.market_maker import MarketMaker

    console.print(Panel(
        "[bold]Market Making Scanner[/bold]\nFind best markets for spread earning",
        border_style="cyan",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        mm = MarketMaker()
        candidates = mm.select_markets(markets, min_volume=min_volume)

        if not candidates:
            console.print("[yellow]No suitable markets for market making[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Market Making Candidates", show_lines=True)
        table.add_column("Market", style="cyan", max_width=40)
        table.add_column("YES", justify="right")
        table.add_column("Volume 24h", justify="right")
        table.add_column("Liquidity", justify="right")
        table.add_column("Bid", justify="right", style="green")
        table.add_column("Ask", justify="right", style="red")
        table.add_column("Spread", justify="right")

        for m in candidates:
            quotes = mm.generate_quotes(m)
            bid = quotes.bid_yes.price if quotes.bid_yes else 0
            ask = quotes.ask_yes.price if quotes.ask_yes else 0

            table.add_row(
                m.question[:40],
                f"{m.yes_price:.3f}",
                f"${m.volume_24h:,.0f}",
                f"${m.liquidity:,.0f}",
                f"{bid:.4f}",
                f"{ask:.4f}",
                f"{quotes.spread:.4f}",
            )
        console.print(table)


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to record")
def record_prices(max_markets: int) -> None:
    """Record current prices to history database for trend analysis."""
    config = Config.from_env()

    from polymarket_bot.price_history import PriceHistoryDB

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)

        db = PriceHistoryDB()
        try:
            count = db.record_prices(markets)
            console.print(f"[green]Recorded {count} market prices to history database[/green]")

            slugs = db.get_tracked_slugs()
            console.print(f"[dim]Total markets tracked: {len(slugs)}[/dim]")
        finally:
            db.close()


@main.command()
@click.argument("slug")
def trend(slug: str) -> None:
    """Show price trend analysis for a market."""
    config = Config.from_env()

    from polymarket_bot.price_history import PriceHistoryDB

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

        db = PriceHistoryDB()
        try:
            t = db.analyze_trend(m)
        finally:
            db.close()

        signal_colors = {
            "STRONG_BUY": "bold green",
            "BUY": "green",
            "HOLD": "yellow",
            "SELL": "red",
            "STRONG_SELL": "bold red",
        }
        sig_color = signal_colors.get(t.signal, "white")

        console.print(Panel(f"[bold]{m.question}[/bold]", border_style="cyan"))
        console.print(f"  Current: {t.current_price:.4f}")
        console.print(f"  1h ago: {t.price_1h_ago:.4f}" if t.price_1h_ago else "  1h ago: N/A")
        console.print(f"  24h ago: {t.price_24h_ago:.4f}" if t.price_24h_ago else "  24h ago: N/A")
        console.print(f"  7d ago: {t.price_7d_ago:.4f}" if t.price_7d_ago else "  7d ago: N/A")
        console.print(f"\n  Trend 1h: {t.trend_1h:+.1%}")
        console.print(f"  Trend 24h: {t.trend_24h:+.1%}")
        console.print(f"  Trend 7d: {t.trend_7d:+.1%}")
        console.print(f"  Volatility 24h: {t.volatility_24h:.4f}")
        console.print(f"  Volume trend: {t.volume_trend:+.1%}")
        console.print(f"  Support: {t.support_level:.4f} | Resistance: {t.resistance_level:.4f}")
        console.print(f"\n  Signal: [{sig_color}]{t.signal}[/{sig_color}]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to monitor")
@click.option("--interval", "-i", default=5.0, help="Poll interval in seconds")
@click.option("--duration", "-d", default=300, help="Duration in seconds")
def realtime(max_markets: int, interval: float, duration: int) -> None:
    """Real-time price monitoring with instant arbitrage detection."""
    config = Config.from_env()

    from polymarket_bot.websocket_stream import create_price_monitor

    console.print(Panel(
        f"[bold]Real-Time Monitor[/bold]\n"
        f"Polling every {interval}s for {duration}s | Markets: {max_markets}\n"
        f"Press Ctrl+C to stop",
        border_style="magenta",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Monitoring {len(markets)} markets[/dim]")

        monitor = create_price_monitor(markets)
        registered = len(monitor._market_tokens)
        console.print(f"[dim]Registered {registered} binary markets[/dim]")

        def on_arb(alert):
            console.print(
                f"[bold red]ARB DETECTED![/bold red] {alert.market_question[:50]} | "
                f"YES={alert.yes_price:.3f} NO={alert.no_price:.3f} = {alert.price_sum:.3f} | "
                f"Profit: {alert.profit_pct:.2f}%"
            )

        monitor.on_alert(on_arb)

        max_iters = int(duration / interval)
        try:
            monitor.start_polling(client, interval=interval, max_iterations=max_iters)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitor stopped[/yellow]")
        finally:
            monitor.stop()

        alerts = monitor.get_recent_alerts()
        console.print(f"\n[bold]Detected {len(alerts)} arbitrage opportunities[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=30, help="Max markets to scan orderbooks")
@click.option("--whale-threshold", default=500.0, help="Min USD for whale order")
def whales(max_markets: int, whale_threshold: float) -> None:
    """Detect smart money positioning via CLOB orderbook whale analysis."""
    config = Config.from_env()

    from polymarket_bot.whale_tracker import WhaleTracker

    console.print(Panel(
        f"[bold]Whale Tracker[/bold]\n"
        f"Scanning top {max_markets} markets for large orders (>${whale_threshold:.0f})",
        border_style="bold red",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        tracker = WhaleTracker(whale_threshold_usd=whale_threshold)
        signals = tracker.scan_markets(client, markets, max_scan=max_markets)

        if not signals:
            console.print("[yellow]No whale activity detected[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Whale Signals", show_lines=True)
        table.add_column("Signal", style="bold")
        table.add_column("Market", style="cyan", max_width=35)
        table.add_column("Side")
        table.add_column("Whale $", justify="right", style="bold green")
        table.add_column("% Book", justify="right")
        table.add_column("Imbalance", justify="right")
        table.add_column("Action", max_width=30)

        for sig in signals[:15]:
            table.add_row(
                sig.signal,
                sig.question[:35],
                sig.side,
                f"${sig.whale_size_usd:,.0f}",
                f"{sig.whale_pct:.0%}",
                f"{sig.imbalance_ratio:.1f}x",
                sig.recommended_action[:30],
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(signals)} whale signals[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--max-days", default=14.0, help="Max days to expiration")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
def decay(max_markets: int, max_days: float, bankroll: float) -> None:
    """Find time-decay opportunities (low-prob near expiry = near-free money)."""
    if bankroll <= 0:
        console.print("[red]Bankroll must be positive[/red]")
        return
    config = Config.from_env()

    from polymarket_bot.decay_harvester import DecayHarvester

    console.print(Panel(
        f"[bold]Decay Harvester[/bold]\n"
        f"Finding low-probability markets expiring within {max_days:.0f} days\n"
        f"Bankroll: ${bankroll:,.0f}",
        border_style="bold yellow",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        harvester = DecayHarvester(
            max_days=max_days, bankroll=bankroll,
        )
        opps = harvester.scan(markets)

        if not opps:
            console.print(
                "[yellow]No decay opportunities found "
                "(no low-prob markets near expiration)[/yellow]"
            )
            return

        from rich.table import Table
        table = Table(title="Decay Opportunities (Time Decay = Free Money)", show_lines=True)
        table.add_column("Market", style="cyan", max_width=35)
        table.add_column("YES $", justify="right")
        table.add_column("Days", justify="right")
        table.add_column("Return/yr", justify="right", style="bold green")
        table.add_column("$/unit", justify="right")
        table.add_column("Bet", justify="right", style="green")
        table.add_column("Side")
        table.add_column("Risk", justify="center")

        for opp in opps[:15]:
            risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(
                opp.risk_level, "white",
            )
            table.add_row(
                opp.question[:35],
                f"{opp.yes_price:.1%}",
                f"{opp.days_to_expiry:.1f}",
                f"{opp.annualized_return_pct:.0f}%",
                f"${opp.profit_per_dollar:.4f}",
                f"${opp.recommended_bet_usd:.0f}",
                opp.recommended_side,
                f"[{risk_color}]{opp.risk_level}[/{risk_color}]",
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(opps)} decay opportunities[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets to analyze")
@click.option("--min-volume", default=5000.0, help="Min 24h volume")
def anomalies(max_markets: int, min_volume: float) -> None:
    """Detect unusual volume patterns signaling insider activity."""
    config = Config.from_env()

    from polymarket_bot.volume_anomaly import VolumeAnomalyDetector

    console.print(Panel(
        f"[bold]Volume Anomaly Detector[/bold]\n"
        f"Scanning {max_markets} markets for unusual trading patterns",
        border_style="bold magenta",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        detector = VolumeAnomalyDetector(min_volume=min_volume)
        results = detector.scan(markets)

        if not results:
            console.print("[yellow]No volume anomalies detected[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Volume Anomalies", show_lines=True)
        table.add_column("Type", style="bold")
        table.add_column("Market", style="cyan", max_width=35)
        table.add_column("Vol 24h", justify="right")
        table.add_column("V/L", justify="right")
        table.add_column("Score", justify="right", style="bold yellow")
        table.add_column("Dir")
        table.add_column("Action", max_width=35)

        for a in results[:15]:
            table.add_row(
                a.anomaly_type,
                a.question[:35],
                f"${a.volume_24h:,.0f}",
                f"{a.volume_liquidity_ratio:.1f}x",
                f"{a.anomaly_score:.1f}",
                a.price_direction,
                a.recommended_action[:35],
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(results)} anomalies[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=20, help="Max markets to check news for")
@click.option("--max-hours", default=48.0, help="Max news age in hours")
def news(max_markets: int, max_hours: float) -> None:
    """Scan breaking news that could move market prices."""
    config = Config.from_env()

    from polymarket_bot.news_sentiment import NewsSentimentScanner

    console.print(Panel(
        f"[bold]News Sentiment Scanner[/bold]\n"
        f"Checking top {max_markets} markets for recent news (<{max_hours:.0f}h)",
        border_style="bold blue",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        scanner = NewsSentimentScanner(max_age_hours=max_hours)
        try:
            matches = scanner.scan_markets(markets, max_scan=max_markets)
        finally:
            scanner.close()

        if not matches:
            console.print("[yellow]No relevant news found for tracked markets[/yellow]")
            return

        from rich.table import Table
        table = Table(title="News Matches", show_lines=True)
        table.add_column("Market", style="cyan", max_width=30)
        table.add_column("Headline", max_width=35)
        table.add_column("Source", style="dim")
        table.add_column("Age", justify="right")
        table.add_column("Sent.")
        table.add_column("Action", max_width=30)

        for m in matches[:15]:
            sent_color = {
                "POSITIVE": "green", "NEGATIVE": "red", "NEUTRAL": "yellow",
            }.get(m.sentiment, "white")
            table.add_row(
                m.question[:30],
                m.headline[:35],
                m.source[:15],
                f"{m.hours_ago:.0f}h",
                f"[{sent_color}]{m.sentiment}[/{sent_color}]",
                m.recommended_action[:30],
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(matches)} news matches[/bold]")


# ── Private Profit Commands ─────────────────────────────────────────


@main.command(name="safe-arb")
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
def safe_arb(max_markets: int, bankroll: float) -> None:
    """Guaranteed arbitrage with exact position sizing after fees."""
    if bankroll <= 0:
        console.print("[bold red]Error: bankroll must be positive[/bold red]")
        return
    config = Config.from_env()

    from polymarket_bot.safe_arb import SafeArbEngine

    console.print(Panel(
        f"[bold]Safe Arbitrage Engine[/bold]\n"
        f"Exact sizing with fee calculation | Bankroll: ${bankroll:,.0f}",
        border_style="bold green",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        engine = SafeArbEngine(bankroll=bankroll)
        positions = engine.scan(client, markets)

        if not positions:
            console.print("[yellow]No guaranteed arb opportunities after fees[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Safe Arbitrage Positions", show_lines=True)
        table.add_column("Market", style="cyan", max_width=35)
        table.add_column("YES", justify="right")
        table.add_column("NO", justify="right")
        table.add_column("Sum", justify="right")
        table.add_column("Cost", justify="right")
        table.add_column("Fees", justify="right", style="dim")
        table.add_column("Net $", justify="right", style="bold green")
        table.add_column("ROI%", justify="right")

        for p in positions[:15]:
            table.add_row(
                p.question[:35],
                f"{p.yes_price:.3f}",
                f"{p.no_price:.3f}",
                f"{p.price_sum:.3f}",
                f"${p.total_cost:.2f}",
                f"${p.total_fees:.2f}",
                f"${p.net_profit:.2f}",
                f"{p.net_profit_pct:.1f}%",
            )
        console.print(table)
        total_profit = sum(p.net_profit for p in positions)
        console.print(
            f"\n[bold green]Found {len(positions)} safe arb positions | "
            f"Total net profit: ${total_profit:.2f}[/bold green]"
        )


@main.command()
@click.option("--max-markets", "-n", default=100, help="Max markets to scan")
@click.option("--min-correlation", default=0.5, help="Min correlation threshold")
def hedge(max_markets: int, min_correlation: float) -> None:
    """Find hedging opportunities across correlated markets."""
    config = Config.from_env()

    from polymarket_bot.hedge_engine import HedgeEngine

    console.print(Panel(
        f"[bold]Hedge Engine[/bold]\n"
        f"Min correlation: {min_correlation} | Scanning {max_markets} markets",
        border_style="bold yellow",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        engine = HedgeEngine(min_correlation=min_correlation)
        hedges = engine.find_all_hedges(markets)

        if not hedges:
            console.print("[yellow]No hedge pairs found[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Hedge Pairs", show_lines=True)
        table.add_column("Type", style="bold")
        table.add_column("Primary", style="cyan", max_width=25)
        table.add_column("Side")
        table.add_column("Hedge", style="magenta", max_width=25)
        table.add_column("Side")
        table.add_column("Corr", justify="right")
        table.add_column("Max Loss", justify="right", style="red")
        table.add_column("E[P]", justify="right", style="green")

        for h in hedges[:15]:
            table.add_row(
                h.hedge_type,
                h.primary_question[:25],
                h.primary_side,
                h.hedge_question[:25],
                h.hedge_side,
                f"{h.correlation:.2f}",
                f"{h.max_loss_pct:+.1f}%",
                f"{h.expected_profit_pct:+.1f}%",
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(hedges)} hedge pairs[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--min-certainty", default=0.93, help="Min certainty threshold (0-1)")
@click.option("--max-hours", default=72.0, help="Max hours to resolution")
@click.option("--bankroll", "-b", default=1000.0, help="Your bankroll")
def sniper(max_markets: int, min_certainty: float, max_hours: float, bankroll: float) -> None:
    """Snipe near-certain outcomes close to market resolution."""
    if bankroll <= 0:
        console.print("[bold red]Error: bankroll must be positive[/bold red]")
        return
    config = Config.from_env()

    from polymarket_bot.resolution_sniper import ResolutionSniper

    console.print(Panel(
        f"[bold]Resolution Sniper[/bold]\n"
        f"Certainty ≥{min_certainty:.0%} | Within {max_hours:.0f}h of resolution | "
        f"Bankroll: ${bankroll:,.0f}",
        border_style="bold magenta",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        sniper_engine = ResolutionSniper(
            min_certainty=min_certainty,
            max_hours=max_hours,
            bankroll=bankroll,
        )
        targets = sniper_engine.scan(markets)

        if not targets:
            console.print("[yellow]No sniper targets found[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Sniper Targets", show_lines=True)
        table.add_column("Market", style="cyan", max_width=30)
        table.add_column("Side", style="bold")
        table.add_column("Price", justify="right")
        table.add_column("Profit/$100", justify="right", style="green")
        table.add_column("Hours", justify="right")
        table.add_column("Risk", style="bold")
        table.add_column("Bet $", justify="right")

        for t in targets[:15]:
            risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(
                t.risk_level, "white",
            )
            table.add_row(
                t.question[:30],
                t.likely_outcome,
                f"{t.outcome_price:.1%}",
                f"${t.net_profit_per_100:.2f}",
                f"{t.hours_to_resolution:.0f}h",
                f"[{risk_color}]{t.risk_level}[/{risk_color}]",
                f"${t.recommended_bet:.0f}",
            )
        console.print(table)
        total_bet = sum(t.recommended_bet for t in targets)
        console.print(
            f"\n[bold]Found {len(targets)} sniper targets | "
            f"Total recommended: ${total_bet:.0f}[/bold]"
        )


@main.command(name="exit-rules")
@click.option("--max-markets", "-n", default=50, help="Max markets to evaluate")
@click.option("--stop-loss", default=10.0, help="Stop-loss trigger %")
@click.option("--take-profit", default=20.0, help="Take-profit trigger %")
@click.option("--trailing-stop", default=8.0, help="Trailing stop %")
def exit_rules(
    max_markets: int, stop_loss: float, take_profit: float, trailing_stop: float,
) -> None:
    """Simulate exit strategy rules (stop-loss, take-profit, trailing stop)."""
    config = Config.from_env()

    from polymarket_bot.exit_strategy import ExitConfig, ExitStrategyEngine

    console.print(Panel(
        f"[bold]Exit Strategy Engine[/bold]\n"
        f"Stop-loss: {stop_loss}% | Take-profit: {take_profit}% | "
        f"Trailing: {trailing_stop}%",
        border_style="bold red",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        exit_config = ExitConfig(
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            trailing_stop_pct=trailing_stop,
        )
        engine = ExitStrategyEngine(config=exit_config)
        rules = engine.simulate_exits(markets)

        if not rules:
            console.print("[yellow]No exit signals triggered[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Exit Signals", show_lines=True)
        table.add_column("Type", style="bold")
        table.add_column("Action", style="cyan", max_width=35)
        table.add_column("Entry", justify="right")
        table.add_column("Now", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Urgency", style="bold")

        for r in rules[:15]:
            pnl_color = "green" if r.pnl_pct >= 0 else "red"
            urg_color = {"IMMEDIATE": "red", "SOON": "yellow", "WATCH": "dim"}.get(
                r.urgency, "white",
            )
            table.add_row(
                r.rule_type,
                r.action[:35],
                f"{r.entry_price:.3f}",
                f"{r.current_price:.3f}",
                f"[{pnl_color}]{r.pnl_pct:+.1f}%[/{pnl_color}]",
                f"[{urg_color}]{r.urgency}[/{urg_color}]",
            )
        console.print(table)
        console.print(f"\n[bold]Found {len(rules)} exit signals[/bold]")


@main.command()
@click.option("--max-markets", "-n", default=200, help="Max markets to scan")
@click.option("--max-combos", default=20, help="Max combos to show")
def combos(max_markets: int, max_combos: int) -> None:
    """Find risk-free multi-market combo positions."""
    config = Config.from_env()

    from polymarket_bot.riskfree_combo import RiskFreeComboEngine

    console.print(Panel(
        f"[bold]Risk-Free Combo Scanner[/bold]\n"
        f"Scanning {max_markets} markets for guaranteed multi-leg positions",
        border_style="bold green",
    ))

    with PolymarketClient(config) as client:
        markets = client.get_all_active_markets(max_markets)
        console.print(f"[dim]Loaded {len(markets)} markets[/dim]")

        engine = RiskFreeComboEngine()
        combos_list = engine.scan(markets, max_combos=max_combos)

        if not combos_list:
            console.print("[yellow]No risk-free combos found[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Risk-Free Combos", show_lines=True)
        table.add_column("Type", style="bold")
        table.add_column("Combo", style="cyan", max_width=30)
        table.add_column("Legs")
        table.add_column("Cost/$100", justify="right")
        table.add_column("Min Pay", justify="right")
        table.add_column("Profit", justify="right", style="bold green")
        table.add_column("ROI%", justify="right")

        for c in combos_list[:15]:
            table.add_row(
                c.combo_type,
                c.name[:30],
                str(len(c.legs)),
                f"${c.total_cost_per_100:.2f}",
                f"${c.min_payout:.2f}",
                f"${c.guaranteed_profit:.2f}",
                f"{c.profit_pct:.1f}%",
            )
        console.print(table)
        total_profit = sum(c.guaranteed_profit for c in combos_list)
        console.print(
            f"\n[bold green]Found {len(combos_list)} risk-free combos | "
            f"Total guaranteed profit: ${total_profit:.2f}/100$[/bold green]"
        )


if __name__ == "__main__":
    main()
