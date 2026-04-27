"""Tests for portfolio optimization module."""

from polymarket_bot.portfolio import (
    PortfolioLimits,
    PortfolioManager,
    optimize_alerts,
)
from polymarket_bot.smart_alerts import Alert, AlertPriority


def _make_alert(
    bet: float = 50.0, profit: float = 5.0, slug: str = "test",
) -> Alert:
    return Alert(
        priority=AlertPriority.HIGH,
        alert_type="SIGNAL",
        title="Test",
        market_question="Will X happen?",
        expected_profit_usd=profit,
        recommended_bet_usd=bet,
        confidence=0.7,
        details="test",
        market_slug=slug,
    )


def test_basic_allocation():
    pm = PortfolioManager(bankroll=1000.0)
    alert = _make_alert(bet=50)
    result = pm.check_allocation(alert, category="crypto")
    assert result.approved is True
    assert result.adjusted_bet_usd <= 100


def test_max_single_bet_limit():
    pm = PortfolioManager(bankroll=1000.0)
    alert = _make_alert(bet=500)
    result = pm.check_allocation(alert)
    assert result.adjusted_bet_usd <= 100  # max 10%


def test_portfolio_full():
    pm = PortfolioManager(bankroll=1000.0)
    for i in range(10):
        pm.add_position(f"market-{i}", "YES", 0.5, 80, "crypto")
    # 800 invested = 80%
    alert = _make_alert(bet=50)
    result = pm.check_allocation(alert)
    assert result.approved is False


def test_theme_limit():
    limits = PortfolioLimits(max_theme_pct=0.20)
    pm = PortfolioManager(bankroll=1000.0, limits=limits)
    pm.add_position("m1", "YES", 0.5, 200, "crypto", "bitcoin")
    # bitcoin theme at 200 = 20%
    alert = _make_alert(bet=50)
    result = pm.check_allocation(alert, theme="bitcoin")
    assert result.approved is False


def test_category_limit():
    limits = PortfolioLimits(max_category_pct=0.10)
    pm = PortfolioManager(bankroll=1000.0, limits=limits)
    pm.add_position("m1", "YES", 0.5, 100, "crypto")
    alert = _make_alert(bet=50)
    result = pm.check_allocation(alert, category="crypto")
    assert result.approved is False


def test_add_remove_position():
    pm = PortfolioManager(bankroll=1000.0)
    pm.add_position("m1", "YES", 0.5, 50, "crypto")
    assert pm.total_invested == 50
    pm.remove_position("m1")
    assert pm.total_invested == 0


def test_get_summary():
    pm = PortfolioManager(bankroll=1000.0)
    pm.add_position("m1", "YES", 0.5, 100, "crypto", "bitcoin")
    pm.add_position("m2", "NO", 0.3, 50, "sports", "soccer")
    summary = pm.get_summary()
    assert summary["total_invested"] == 150
    assert summary["num_positions"] == 2
    assert "crypto" in summary["by_category"]


def test_optimize_alerts():
    alerts = [
        _make_alert(bet=50, slug="m1"),
        _make_alert(bet=50, slug="m2"),
        _make_alert(bet=50, slug="m3"),
    ]
    results = optimize_alerts(alerts, bankroll=1000.0)
    assert len(results) == 3
    approved = [r for _, r in results if r.approved]
    assert len(approved) >= 1


def test_portfolio_state_roundtrip():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
        pm1 = PortfolioManager(bankroll=2000.0, state_path=path)
        pm1.add_position("m1", "YES", 0.5, 100, "crypto")
        pm1.save_state()

        pm2 = PortfolioManager(state_path=path)
        loaded = pm2.load_state()
        assert loaded is True
        assert pm2.bankroll == 2000.0
        assert len(pm2.positions) == 1
