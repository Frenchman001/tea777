"""Tests for signal analyzer."""

from polymarket_bot.config import Config
from polymarket_bot.models import Market, SignalType, Token
from polymarket_bot.signals import SignalAnalyzer


class FakeClient:
    def __init__(self):
        self.config = Config()

    def get_all_active_markets(self, max_markets=None):
        return []


def _make_market(yes_price: float, no_price: float, **kwargs) -> Market:
    defaults = {
        "condition_id": "test",
        "question": "Test market?",
        "slug": "test-market",
        "volume": 100000,
        "volume_24h": 5000,
    }
    defaults.update(kwargs)
    return Market(
        **defaults,
        tokens=[
            Token(token_id="yes_token", outcome="Yes", price=yes_price),
            Token(token_id="no_token", outcome="No", price=no_price),
        ],
    )


def test_detects_overpriced_market():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.60, 0.50)  # sum = 1.10
    signals = analyzer.analyze_markets([market])

    overvalued = [s for s in signals if s.signal_type == SignalType.OVERVALUED]
    assert len(overvalued) >= 1


def test_detects_underpriced_market():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.40, 0.45)  # sum = 0.85
    signals = analyzer.analyze_markets([market])

    undervalued = [s for s in signals if s.signal_type == SignalType.UNDERVALUED]
    assert len(undervalued) >= 1


def test_detects_extreme_high():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.97, 0.03)
    signals = analyzer.analyze_markets([market])

    extreme = [s for s in signals if s.signal_type == SignalType.OVERVALUED]
    assert len(extreme) >= 1


def test_detects_extreme_low():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.02, 0.98)
    signals = analyzer.analyze_markets([market])

    undervalued = [s for s in signals if s.signal_type == SignalType.UNDERVALUED]
    assert len(undervalued) >= 1


def test_detects_volume_anomaly():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    # volume_24h is 50000, total volume is 100000
    # Estimated age ~30 days -> avg daily ~3333 -> ratio ~15x
    market = _make_market(0.55, 0.45, volume=100000, volume_24h=50000)
    signals = analyzer.analyze_markets([market])

    momentum = [s for s in signals if s.signal_type == SignalType.MOMENTUM]
    assert len(momentum) >= 1


def test_no_signal_for_fair_market():
    config = Config(min_confidence=0.6)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    market = _make_market(0.50, 0.50, volume=100000, volume_24h=3000)
    signals = analyzer.analyze_markets([market])

    assert len(signals) == 0


def test_signals_sorted_by_confidence():
    config = Config(min_confidence=0.1)
    analyzer = SignalAnalyzer(FakeClient(), config)  # type: ignore[arg-type]

    markets = [
        _make_market(0.60, 0.50, condition_id="m1", slug="m1"),
        _make_market(0.40, 0.30, condition_id="m2", slug="m2"),
        _make_market(0.97, 0.03, condition_id="m3", slug="m3"),
    ]
    signals = analyzer.analyze_markets(markets)

    for i in range(len(signals) - 1):
        assert signals[i].confidence >= signals[i + 1].confidence
