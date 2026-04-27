"""Tests for whale tracker module."""

from polymarket_bot.models import Market, OrderBook, OrderBookLevel, Token
from polymarket_bot.whale_tracker import WhaleSignal, WhaleTracker


def _make_market(yes_price: float = 0.5) -> Market:
    return Market(
        condition_id="c1", question="Test?", slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=yes_price),
            Token(token_id="t2", outcome="No", price=1 - yes_price),
        ],
        volume_24h=50000,
    )


def _make_book(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> OrderBook:
    return OrderBook(
        token_id="t1",
        bids=[OrderBookLevel(price=p, size=s) for p, s in bids],
        asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
    )


def test_whale_signal_description():
    sig = WhaleSignal(
        market_slug="test", question="Will X happen?",
        signal="WHALE_BID", side="YES",
        whale_size_usd=2000, total_book_usd=5000,
        whale_pct=0.4, imbalance_ratio=3.0,
        current_price=0.5,
        recommended_action="BUY YES @ 0.500",
        confidence=0.7,
    )
    assert "WHALE_BID" in sig.description
    assert "$2000" in sig.description


def test_distribution_empty():
    tracker = WhaleTracker()
    dist = tracker._distribution([])
    assert dist.total_usd == 0
    assert dist.whale_pct == 0


def test_distribution_with_whale():
    tracker = WhaleTracker(whale_threshold_usd=100)
    levels = [
        OrderBookLevel(price=0.5, size=1000),  # 500 usd — whale
        OrderBookLevel(price=0.5, size=10),     # 5 usd — not whale
    ]
    dist = tracker._distribution(levels)
    assert dist.large_order_count == 1
    assert dist.large_order_usd == 500
    assert dist.whale_pct > 0.9


def test_analyze_book_whale_bid():
    tracker = WhaleTracker(whale_threshold_usd=100, imbalance_threshold=1.5)
    market = _make_market(0.5)
    book = _make_book(
        bids=[(0.5, 2000)],  # $1000 bid — whale
        asks=[(0.5, 100)],    # $50 ask
    )
    signals = tracker._analyze_book(book, market)
    whale_bids = [s for s in signals if s.signal == "WHALE_BID"]
    assert len(whale_bids) >= 1
    assert whale_bids[0].side == "YES"


def test_analyze_book_no_whale():
    tracker = WhaleTracker(whale_threshold_usd=10000)
    market = _make_market(0.5)
    book = _make_book(
        bids=[(0.5, 10)],
        asks=[(0.5, 10)],
    )
    signals = tracker._analyze_book(book, market)
    assert len(signals) == 0


def test_analyze_empty_book():
    tracker = WhaleTracker()
    market = _make_market(0.5)
    book = _make_book([], [])
    signals = tracker._analyze_book(book, market)
    assert len(signals) == 0
