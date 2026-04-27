"""Tests for arbitrage scanner."""

from polymarket_bot.arbitrage import ArbitrageScanner
from polymarket_bot.config import Config
from polymarket_bot.models import Market, Token


class FakeClient:
    """Fake client for testing without network calls."""

    def __init__(self):
        self.config = Config()

    def get_all_active_markets(self, max_markets=None):
        return []


def _make_market(yes_price: float, no_price: float, volume_24h: float = 1000.0, **kwargs) -> Market:
    defaults = {
        "condition_id": "test",
        "question": "Test market?",
        "slug": "test-market",
        "active": True,
        "closed": False,
        "volume_24h": volume_24h,
        "liquidity": 10000.0,
    }
    defaults.update(kwargs)
    return Market(
        **defaults,
        tokens=[
            Token(token_id="yes_token", outcome="Yes", price=yes_price),
            Token(token_id="no_token", outcome="No", price=no_price),
        ],
    )


def test_finds_arbitrage_when_sum_below_one():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.45, 0.50, volume_24h=500)
    opps = scanner.scan([market])

    assert len(opps) == 1
    assert opps[0].profit_pct == (1.0 - 0.95) * 100
    assert opps[0].guaranteed_profit == 1.0 - 0.95


def test_no_arbitrage_when_sum_above_threshold():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.50, 0.50, volume_24h=500)
    opps = scanner.scan([market])

    assert len(opps) == 0


def test_filters_low_volume():
    config = Config(min_profit_pct=0.5, min_volume_24h=1000, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.45, 0.50, volume_24h=100)
    opps = scanner.scan([market])

    assert len(opps) == 0


def test_filters_inactive_markets():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.45, 0.50, volume_24h=500, active=False)
    opps = scanner.scan([market])

    assert len(opps) == 0


def test_filters_closed_markets():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.45, 0.50, volume_24h=500, closed=True)
    opps = scanner.scan([market])

    assert len(opps) == 0


def test_sorts_by_profit_descending():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    markets = [
        _make_market(0.47, 0.48, volume_24h=500, condition_id="m1", slug="m1"),  # 5% profit
        _make_market(0.40, 0.40, volume_24h=500, condition_id="m2", slug="m2"),  # 20% profit
        _make_market(0.45, 0.50, volume_24h=500, condition_id="m3", slug="m3"),  # 5% profit
    ]
    opps = scanner.scan(markets)

    assert len(opps) == 3
    assert opps[0].profit_pct >= opps[1].profit_pct
    assert opps[1].profit_pct >= opps[2].profit_pct


def test_liquidity_score():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.45, 0.50, volume_24h=500, liquidity=25000)
    opps = scanner.scan([market])

    assert len(opps) == 1
    assert opps[0].liquidity_score == 0.5


def test_handles_zero_prices():
    config = Config(min_profit_pct=0.5, min_volume_24h=100, max_price_sum=0.995)
    scanner = ArbitrageScanner(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.0, 0.50, volume_24h=500)
    opps = scanner.scan([market])

    assert len(opps) == 0
