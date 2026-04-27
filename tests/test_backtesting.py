"""Tests for backtesting engine."""

from polymarket_bot.backtesting import BacktestEngine, BacktestResult, BacktestTrade
from polymarket_bot.models import Market, Token


def _resolved_market(
    slug: str, question: str,
    yes_price: float, winner: str,
) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        question=question,
        slug=slug,
        tokens=[
            Token(token_id=f"y-{slug}", outcome="Yes",
                  price=yes_price, winner=(winner == "YES")),
            Token(token_id=f"n-{slug}", outcome="No",
                  price=1 - yes_price, winner=(winner == "NO")),
        ],
        volume_24h=10000,
    )


def test_kelly_strategy_basic():
    markets = [
        _resolved_market("m1", "BTC $100k?", 0.6, "YES"),
        _resolved_market("m2", "ETH $10k?", 0.3, "NO"),
        _resolved_market("m3", "SOL $500?", 0.5, "YES"),
    ]
    from unittest.mock import MagicMock

    from polymarket_bot.config import Config
    client = MagicMock()
    bt = BacktestEngine(client, Config(), bankroll=1000)
    result = bt.run_kelly_strategy(markets)
    assert isinstance(result, BacktestResult)
    assert result.strategy_name == "Kelly Criterion"


def test_arbitrage_strategy():
    markets = [
        Market(
            condition_id="c1", question="Test?", slug="arb1",
            tokens=[
                Token(token_id="y1", outcome="Yes", price=0.45),
                Token(token_id="n1", outcome="No", price=0.45),
            ],
            volume_24h=5000,
        ),
    ]
    from unittest.mock import MagicMock

    from polymarket_bot.config import Config
    client = MagicMock()
    bt = BacktestEngine(client, Config(), bankroll=1000)
    result = bt.run_arbitrage_strategy(markets)
    assert result.strategy_name == "Arbitrage"
    if result.trades_taken > 0:
        assert result.net_pnl > 0


def test_value_strategy():
    markets = [
        _resolved_market("m1", "Longshot?", 0.05, "YES"),
        _resolved_market("m2", "Favorite?", 0.95, "YES"),
    ]
    from unittest.mock import MagicMock

    from polymarket_bot.config import Config
    client = MagicMock()
    bt = BacktestEngine(client, Config(), bankroll=1000)
    result = bt.run_value_strategy(markets)
    assert result.strategy_name == "Value Betting"


def test_backtest_trade_net_pnl():
    t = BacktestTrade(
        market_slug="s", question="q", side="YES",
        entry_price=0.5, bet_usd=100, won=True,
        pnl=100.0, fee=2.0,
    )
    assert t.net_pnl == 98.0


def test_backtest_result_roi():
    r = BacktestResult(
        strategy_name="Test", total_markets=10, trades_taken=2,
        wins=1, losses=1, total_pnl=20.0, total_fees=2.0,
        net_pnl=18.0, win_rate=0.5, avg_pnl_per_trade=9.0,
        max_drawdown=0.1, sharpe_ratio=1.0,
        trades=[
            BacktestTrade("s1", "q", "YES", 0.5, 50, True, 30, 1),
            BacktestTrade("s2", "q", "NO", 0.5, 50, False, -10, 1),
        ],
    )
    assert r.roi_pct > 0


def test_no_resolved_markets():
    markets = [
        Market(
            condition_id="c1", question="Active?", slug="active",
            tokens=[
                Token(token_id="y1", outcome="Yes", price=0.5),
                Token(token_id="n1", outcome="No", price=0.5),
            ],
        ),
    ]
    from unittest.mock import MagicMock

    from polymarket_bot.config import Config
    client = MagicMock()
    bt = BacktestEngine(client, Config(), bankroll=1000)
    result = bt.run_kelly_strategy(markets)
    assert result.trades_taken == 0
