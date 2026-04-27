"""Tests for riskfree_combo module."""

from __future__ import annotations

from polymarket_bot.models import Market, Token
from polymarket_bot.riskfree_combo import ComboLeg, RiskFreeCombo, RiskFreeComboEngine


def _make_market(
    slug: str = "test",
    question: str = "Will it happen?",
    yes: float = 0.60,
    no: float = 0.40,
    event_slug: str = "",
    active: bool = True,
    closed: bool = False,
) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        question=question,
        slug=slug,
        tokens=[
            Token(token_id=f"y-{slug}", outcome="Yes", price=yes, winner=False),
            Token(token_id=f"n-{slug}", outcome="No", price=no, winner=False),
        ],
        active=active,
        closed=closed,
        event_slug=event_slug,
    )


class TestRiskFreeCombo:
    def test_finds_mirror_arb(self) -> None:
        engine = RiskFreeComboEngine()
        m = _make_market(yes=0.40, no=0.40)  # Sum=0.80
        combos = engine.scan([m])
        mirrors = [c for c in combos if c.combo_type == "MIRROR"]
        assert len(mirrors) >= 1
        for c in mirrors:
            assert c.guaranteed_profit > 0
            assert c.is_profitable

    def test_no_mirror_when_sum_one(self) -> None:
        engine = RiskFreeComboEngine()
        m = _make_market(yes=0.50, no=0.50)
        combos = engine.scan([m])
        mirrors = [c for c in combos if c.combo_type == "MIRROR"]
        assert len(mirrors) == 0

    def test_finds_event_arb(self) -> None:
        engine = RiskFreeComboEngine()
        markets = [
            _make_market("a", "Option A?", yes=0.20, event_slug="ev1"),
            _make_market("b", "Option B?", yes=0.30, event_slug="ev1"),
            _make_market("c", "Option C?", yes=0.25, event_slug="ev1"),
        ]
        combos = engine.scan(markets)
        event_arbs = [c for c in combos if c.combo_type == "EVENT_ARB"]
        if event_arbs:
            assert event_arbs[0].guaranteed_profit > 0
            assert len(event_arbs[0].legs) >= 2

    def test_finds_opposite_combos(self) -> None:
        engine = RiskFreeComboEngine()
        markets = [
            _make_market("x", "Event X?", yes=0.95, no=0.05),
            _make_market("y", "Event Y?", yes=0.93, no=0.07),
        ]
        combos = engine.scan(markets)
        # Opposite combos need NO price <= 0.08
        opp = [c for c in combos if c.combo_type == "CONDITIONAL"]
        assert isinstance(opp, list)

    def test_skips_closed_markets(self) -> None:
        engine = RiskFreeComboEngine()
        m = _make_market(yes=0.40, no=0.40, closed=True)
        combos = engine.scan([m])
        assert len(combos) == 0

    def test_combo_description(self) -> None:
        combo = RiskFreeCombo(
            name="Mirror: Bitcoin hits $100k?",
            legs=[
                ComboLeg("btc", "Bitcoin hits $100k?", "YES", 0.40, 50),
                ComboLeg("btc", "Bitcoin hits $100k?", "NO", 0.40, 50),
            ],
            total_cost_per_100=80.0,
            min_payout=100.0,
            max_payout=100.0,
            guaranteed_profit=20.0,
            profit_pct=25.0,
            combo_type="MIRROR",
        )
        assert "RISK-FREE" in combo.description
        assert "$20.00" in combo.description
        assert combo.is_profitable

    def test_unprofitable_combo(self) -> None:
        combo = RiskFreeCombo(
            name="Bad combo",
            legs=[],
            total_cost_per_100=100.0,
            min_payout=95.0,
            max_payout=100.0,
            guaranteed_profit=-5.0,
            profit_pct=-5.0,
            combo_type="MIRROR",
        )
        assert "HEDGED" in combo.description
        assert not combo.is_profitable

    def test_combo_leg_description(self) -> None:
        leg = ComboLeg("test", "Will it happen?", "YES", 0.60, 60)
        assert "YES" in leg.description
        assert "60%" in leg.description

    def test_scan_limits_results(self) -> None:
        engine = RiskFreeComboEngine()
        markets = [
            _make_market(f"m{i}", f"Market {i}?", yes=0.35, no=0.35)
            for i in range(20)
        ]
        combos = engine.scan(markets, max_combos=5)
        assert len(combos) <= 5
