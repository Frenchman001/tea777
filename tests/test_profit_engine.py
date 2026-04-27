"""Tests for profit engine."""

from polymarket_bot.models import Market, OrderBook, OrderBookLevel, Token
from polymarket_bot.profit_engine import (
    calculate_fee,
    calculate_net_profit,
    estimate_slippage,
    kelly_criterion,
    score_market,
)


def _make_market(yes_price: float, no_price: float, **kwargs) -> Market:
    defaults = {
        "condition_id": "test",
        "question": "Test market?",
        "slug": "test-market",
        "volume": 100000,
        "volume_24h": 5000,
        "liquidity": 10000,
    }
    defaults.update(kwargs)
    return Market(
        **defaults,
        tokens=[
            Token(token_id="yes_token", outcome="Yes", price=yes_price),
            Token(token_id="no_token", outcome="No", price=no_price),
        ],
    )


# ── Fee Tests ──────────────────────────────────────────────────────

def test_fee_geopolitics_is_zero():
    fee = calculate_fee(0.5, 100, "geopolitics")
    assert fee.fee_amount == 0.0
    assert fee.effective_fee_pct == 0.0


def test_fee_rate_peaks_at_50_pct():
    fee_50 = calculate_fee(0.5, 100, "politics")
    fee_80 = calculate_fee(0.8, 100, "politics")
    # Effective fee percentage (not absolute amount) peaks near 50%
    assert fee_50.effective_fee_pct > fee_80.effective_fee_pct


def test_fee_zero_at_extremes():
    fee_0 = calculate_fee(0.0, 100, "politics")
    fee_1 = calculate_fee(1.0, 100, "politics")
    assert fee_0.fee_amount == 0.0
    assert fee_1.fee_amount == 0.0


def test_fee_scales_with_shares():
    fee_100 = calculate_fee(0.5, 100, "crypto")
    fee_200 = calculate_fee(0.5, 200, "crypto")
    assert abs(fee_200.fee_amount - fee_100.fee_amount * 2) < 0.001


# ── Kelly Criterion Tests ──────────────────────────────────────────

def test_kelly_positive_edge():
    sizing = kelly_criterion(0.7, 0.5, bankroll=1000)
    assert sizing.kelly_fraction > 0
    assert sizing.kelly_bet_usd > 0
    assert sizing.edge > 0


def test_kelly_no_edge():
    sizing = kelly_criterion(0.5, 0.5, bankroll=1000)
    assert sizing.kelly_fraction == 0.0
    assert sizing.kelly_bet_usd == 0.0


def test_kelly_negative_edge():
    sizing = kelly_criterion(0.3, 0.5, bankroll=1000)
    assert sizing.kelly_fraction == 0.0
    assert sizing.kelly_bet_usd == 0.0


def test_kelly_half_kelly_is_half():
    sizing = kelly_criterion(0.8, 0.5, bankroll=1000)
    assert abs(sizing.half_kelly_bet_usd - sizing.kelly_bet_usd * 0.5) < 0.01


def test_kelly_max_fraction_cap():
    sizing = kelly_criterion(0.99, 0.1, bankroll=1000, max_fraction=0.25)
    assert sizing.kelly_fraction <= 0.25


def test_kelly_recommended_is_half():
    sizing = kelly_criterion(0.7, 0.4, bankroll=1000)
    assert sizing.recommended_bet_usd == sizing.half_kelly_bet_usd


# ── Slippage Tests ─────────────────────────────────────────────────

def test_slippage_zero_for_small_order():
    book = OrderBook(
        token_id="t1",
        asks=[OrderBookLevel(price=0.5, size=10000)],
        best_ask=0.5,
    )
    slip = estimate_slippage(book, 10.0, side="buy")
    assert slip.slippage_pct == 0.0
    assert slip.levels_consumed == 1


def test_slippage_increases_with_depth():
    book = OrderBook(
        token_id="t1",
        asks=[
            OrderBookLevel(price=0.50, size=100),
            OrderBookLevel(price=0.55, size=100),
            OrderBookLevel(price=0.60, size=100),
        ],
        best_ask=0.50,
    )
    slip_small = estimate_slippage(book, 10.0, side="buy")
    slip_large = estimate_slippage(book, 100.0, side="buy")
    assert slip_large.slippage_pct >= slip_small.slippage_pct


def test_slippage_empty_book():
    book = OrderBook(token_id="t1")
    slip = estimate_slippage(book, 100.0)
    assert slip.fillable_amount == 0.0


# ── Market Score Tests ─────────────────────────────────────────────

def test_score_higher_for_better_edge():
    m_good = _make_market(0.4, 0.5)  # sum < 1, edge
    m_fair = _make_market(0.5, 0.5)  # fair

    score_good = score_market(m_good, estimated_true_prob=0.6)
    score_fair = score_market(m_fair, estimated_true_prob=0.5)

    assert score_good.total_score >= score_fair.total_score


def test_score_includes_all_components():
    m = _make_market(0.5, 0.5, volume_24h=10000, liquidity=50000)
    score = score_market(m, estimated_true_prob=0.7)

    assert score.ev_score >= 0
    assert score.liquidity_score >= 0
    assert score.time_score >= 0
    assert score.volume_score >= 0


def test_net_profit_positive_with_edge():
    profit = calculate_net_profit(0.4, 100, 0.6, "geopolitics")
    assert profit > 0


def test_net_profit_negative_without_edge():
    profit = calculate_net_profit(0.6, 100, 0.4, "crypto")
    assert profit < 0
