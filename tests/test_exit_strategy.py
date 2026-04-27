"""Tests for exit_strategy module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polymarket_bot.exit_strategy import (
    ExitConfig,
    ExitRule,
    ExitStrategyEngine,
    Position,
)
from polymarket_bot.models import Market, Token


def _make_market(
    slug: str = "test",
    question: str = "Will it happen?",
    yes: float = 0.60,
    no: float = 0.40,
    end_hours: float | None = None,
) -> Market:
    end_date = None
    if end_hours is not None:
        end = datetime.now(tz=timezone.utc) + timedelta(hours=end_hours)
        end_date = end.isoformat()
    return Market(
        condition_id="c1",
        question=question,
        slug=slug,
        tokens=[
            Token(token_id="yes1", outcome="Yes", price=yes, winner=False),
            Token(token_id="no1", outcome="No", price=no, winner=False),
        ],
        active=True,
        closed=False,
        end_date=end_date if end_date else "",
    )


class TestExitStrategy:
    def test_stop_loss_triggers(self) -> None:
        engine = ExitStrategyEngine(ExitConfig(stop_loss_pct=10))
        pos = Position("test", "Will it?", "YES", 0.60, 100)
        market = _make_market(yes=0.50)  # -16.7%
        rules = engine._evaluate_position(pos, market, 0.50)
        stop_rules = [r for r in rules if r.rule_type == "STOP_LOSS"]
        assert len(stop_rules) == 1
        assert stop_rules[0].urgency == "IMMEDIATE"

    def test_take_profit_triggers(self) -> None:
        engine = ExitStrategyEngine(ExitConfig(take_profit_pct=20))
        pos = Position("test", "Will it?", "YES", 0.50, 100)
        market = _make_market(yes=0.65)  # +30%
        rules = engine._evaluate_position(pos, market, 0.65)
        tp_rules = [r for r in rules if r.rule_type == "TAKE_PROFIT"]
        assert len(tp_rules) == 1
        assert tp_rules[0].urgency == "SOON"

    def test_trailing_stop_triggers(self) -> None:
        config = ExitConfig(trailing_stop_pct=8)
        engine = ExitStrategyEngine(config)
        pos = Position("test", "Will it?", "YES", 0.50, 100)
        pos.highest_price = 0.70  # Was at 0.70
        market = _make_market(yes=0.60)  # Dropped ~14% from peak
        rules = engine._evaluate_position(pos, market, 0.60)
        ts_rules = [r for r in rules if r.rule_type == "TRAILING_STOP"]
        assert len(ts_rules) == 1

    def test_trailing_stop_not_triggered_at_entry(self) -> None:
        config = ExitConfig(trailing_stop_pct=8)
        engine = ExitStrategyEngine(config)
        pos = Position("test", "Will it?", "YES", 0.50, 100)
        # highest_price defaults to entry_price
        market = _make_market(yes=0.48)
        rules = engine._evaluate_position(pos, market, 0.48)
        ts_rules = [r for r in rules if r.rule_type == "TRAILING_STOP"]
        assert len(ts_rules) == 0

    def test_time_exit_triggers(self) -> None:
        config = ExitConfig(time_exit_hours=24)
        engine = ExitStrategyEngine(config)
        pos = Position("test", "Will it?", "YES", 0.50, 100)
        market = _make_market(yes=0.50, end_hours=12)
        rules = engine._evaluate_position(pos, market, 0.50)
        time_rules = [r for r in rules if r.rule_type == "TIME_EXIT"]
        assert len(time_rules) == 1

    def test_time_exit_no_trigger_far_away(self) -> None:
        config = ExitConfig(time_exit_hours=24)
        engine = ExitStrategyEngine(config)
        pos = Position("test", "Will it?", "YES", 0.50, 100)
        market = _make_market(yes=0.50, end_hours=200)
        rules = engine._evaluate_position(pos, market, 0.50)
        time_rules = [r for r in rules if r.rule_type == "TIME_EXIT"]
        assert len(time_rules) == 0

    def test_simulate_exits(self) -> None:
        engine = ExitStrategyEngine()
        markets = [_make_market(yes=0.60, slug=f"m{i}") for i in range(5)]
        rules = engine.simulate_exits(markets)
        assert isinstance(rules, list)

    def test_check_exits_with_positions(self) -> None:
        engine = ExitStrategyEngine(ExitConfig(stop_loss_pct=5))
        engine.add_position(Position("test", "Will it?", "YES", 0.80, 100))
        markets = [_make_market(yes=0.50)]  # -37.5% from entry
        rules = engine.check_exits(markets)
        assert any(r.rule_type == "STOP_LOSS" for r in rules)

    def test_exit_rule_description(self) -> None:
        rule = ExitRule(
            rule_type="STOP_LOSS",
            trigger_price=0.45,
            current_price=0.40,
            entry_price=0.50,
            pnl_pct=-20.0,
            action="SELL YES on Test Market",
            urgency="IMMEDIATE",
        )
        assert "STOP_LOSS" in rule.description
        assert "IMMEDIATE" in rule.description

    def test_no_rules_on_zero_entry(self) -> None:
        engine = ExitStrategyEngine()
        pos = Position("test", "Test", "YES", 0.0, 100)
        market = _make_market(yes=0.50)
        rules = engine._evaluate_position(pos, market, 0.50)
        assert len(rules) == 0
