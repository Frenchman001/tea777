"""Tests for price history and trend analysis."""

import tempfile
from pathlib import Path

from polymarket_bot.models import Market, Token
from polymarket_bot.price_history import PriceHistoryDB, TrendAnalysis


def _make_market(slug: str = "test", yes_price: float = 0.5) -> Market:
    return Market(
        condition_id="cond1",
        question="Test?",
        slug=slug,
        tokens=[
            Token(token_id="yes1", outcome="Yes", price=yes_price),
            Token(token_id="no1", outcome="No", price=1 - yes_price),
        ],
        volume_24h=1000,
        liquidity=5000,
    )


def test_record_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = PriceHistoryDB(Path(tmpdir) / "test.db")
        try:
            markets = [_make_market("btc", 0.6), _make_market("eth", 0.4)]
            count = db.record_prices(markets)
            assert count == 2

            history = db.get_history("btc", hours=1)
            assert len(history) == 1
            assert history[0].yes_price == 0.6
        finally:
            db.close()


def test_get_price_at():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = PriceHistoryDB(Path(tmpdir) / "test.db")
        try:
            markets = [_make_market("btc", 0.65)]
            db.record_prices(markets)

            price = db.get_price_at("btc", 0)
            assert price == 0.65

            no_price = db.get_price_at("nonexistent", 0)
            assert no_price is None
        finally:
            db.close()


def test_analyze_trend_no_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = PriceHistoryDB(Path(tmpdir) / "test.db")
        try:
            m = _make_market("btc", 0.7)
            t = db.analyze_trend(m)
            assert t.current_price == 0.7
            assert t.signal in ("HOLD", "BUY", "SELL", "STRONG_BUY", "STRONG_SELL")
        finally:
            db.close()


def test_cleanup_old():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = PriceHistoryDB(Path(tmpdir) / "test.db")
        try:
            db.record_prices([_make_market("btc", 0.5)])
            # days=30 means cutoff is 30 days ago — fresh record not deleted
            deleted = db.cleanup_old(days=30)
            assert deleted == 0
            # days=0 means cutoff is now — record IS deleted
            deleted = db.cleanup_old(days=0)
            assert deleted == 1
        finally:
            db.close()


def test_get_tracked_slugs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = PriceHistoryDB(Path(tmpdir) / "test.db")
        try:
            db.record_prices([_make_market("btc", 0.5), _make_market("eth", 0.3)])
            slugs = db.get_tracked_slugs()
            assert "btc" in slugs
            assert "eth" in slugs
        finally:
            db.close()


def test_trend_analysis_properties():
    t = TrendAnalysis(
        slug="test", question="Test?", current_price=0.5,
        price_1h_ago=0.48, price_24h_ago=0.45, price_7d_ago=0.40,
        trend_1h=0.04, trend_24h=0.11, trend_7d=0.25,
        volatility_24h=0.02, volume_trend=0.5,
        support_level=0.40, resistance_level=0.55,
        signal="BUY",
    )
    assert t.is_trending_up is True
    assert t.is_trending_down is False
