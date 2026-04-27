"""Tests for volume anomaly detector module."""

from polymarket_bot.models import Market, Token
from polymarket_bot.volume_anomaly import VolumeAnomaly, VolumeAnomalyDetector


def _make_market(
    vol: float = 10000,
    liq: float = 50000,
    yes_price: float = 0.5,
    question: str = "Test?",
) -> Market:
    return Market(
        condition_id="c1", question=question, slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=yes_price),
            Token(token_id="t2", outcome="No", price=1 - yes_price),
        ],
        volume_24h=vol,
        liquidity=liq,
    )


def test_anomaly_description():
    a = VolumeAnomaly(
        market_slug="test", question="Will X?",
        volume_24h=50000, liquidity=10000,
        volume_liquidity_ratio=5.0,
        price_direction="UP", yes_price=0.8,
        anomaly_score=7.5, anomaly_type="VOLUME_SPIKE",
        recommended_action="BUY YES", confidence=0.7,
    )
    assert "VOLUME_SPIKE" in a.description
    assert "7.5" in a.description


def test_scan_detects_spike():
    detector = VolumeAnomalyDetector(min_volume=1000, spike_threshold=3.0)
    markets = [
        _make_market(vol=100000, liq=50000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
    ]
    results = detector.scan(markets)
    spikes = [r for r in results if r.anomaly_type == "VOLUME_SPIKE"]
    assert len(spikes) >= 1
    assert spikes[0].volume_24h == 100000


def test_scan_detects_high_turnover():
    detector = VolumeAnomalyDetector(min_volume=1000, turnover_threshold=2.0)
    markets = [
        _make_market(vol=50000, liq=5000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
        _make_market(vol=5000, liq=50000),
    ]
    results = detector.scan(markets)
    turnovers = [r for r in results if r.anomaly_type == "HIGH_TURNOVER"]
    assert len(turnovers) >= 1


def test_scan_too_few_markets():
    detector = VolumeAnomalyDetector()
    markets = [_make_market()]
    assert detector.scan(markets) == []


def test_infer_direction():
    detector = VolumeAnomalyDetector()
    assert detector._infer_direction(_make_market(yes_price=0.9)) == "UP"
    assert detector._infer_direction(_make_market(yes_price=0.1)) == "DOWN"
    assert detector._infer_direction(_make_market(yes_price=0.5)) == "NEUTRAL"


def test_no_anomaly_low_volume():
    detector = VolumeAnomalyDetector(min_volume=100000)
    markets = [_make_market(vol=v) for v in [1000, 2000, 3000, 4000, 5000]]
    results = detector.scan(markets)
    assert len(results) == 0
