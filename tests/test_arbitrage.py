"""Tests for the arbitrage engine."""

from src.arbitrage.engine import calculate_arbitrage, optimal_stakes


def test_arbitrage_exists():
    """When combined implied probability < 100%, arbitrage exists."""
    # odds 2.1 and 2.1 => 1/2.1 + 1/2.1 = 0.952 < 1
    profit = calculate_arbitrage(2.1, 2.1)
    assert profit is not None
    assert profit > 0


def test_no_arbitrage():
    """When combined implied probability >= 100%, no arbitrage."""
    profit = calculate_arbitrage(1.8, 1.8)
    assert profit is None


def test_optimal_stakes():
    """Optimal stakes should guarantee profit."""
    stake_a, stake_b, profit = optimal_stakes(2.1, 2.1, 100.0)
    assert stake_a > 0
    assert stake_b > 0
    assert profit > 0
    assert abs(stake_a + stake_b - 100.0) < 0.01

    # Both payouts should be approximately equal
    payout_a = stake_a * 2.1
    payout_b = stake_b * 2.1
    assert abs(payout_a - payout_b) < 0.01


def test_optimal_stakes_no_arb():
    """No arb => zero stakes."""
    stake_a, stake_b, profit = optimal_stakes(1.5, 1.5, 100.0)
    assert stake_a == 0
    assert stake_b == 0
    assert profit == 0


def test_asymmetric_arbitrage():
    """Asymmetric odds should still find arbitrage when it exists."""
    profit = calculate_arbitrage(3.0, 1.6)
    # 1/3.0 + 1/1.6 = 0.333 + 0.625 = 0.958 < 1
    assert profit is not None
    assert profit > 0

    stake_a, stake_b, guaranteed = optimal_stakes(3.0, 1.6, 100.0)
    assert guaranteed > 0
    # Both payouts should be close
    payout_a = stake_a * 3.0
    payout_b = stake_b * 1.6
    assert abs(payout_a - payout_b) < 0.01
