"""Tests for data models."""

from polymarket_bot.models import (
    ArbitrageOpportunity,
    Market,
    SignalStrength,
    SignalType,
    Token,
    TradingSignal,
    parse_json_field,
)


def test_market_yes_no_prices():
    m = Market(
        condition_id="abc",
        question="Test?",
        slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=0.6),
            Token(token_id="t2", outcome="No", price=0.35),
        ],
    )
    assert m.yes_price == 0.6
    assert m.no_price == 0.35


def test_market_price_sum():
    m = Market(
        condition_id="abc",
        question="Test?",
        slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=0.45),
            Token(token_id="t2", outcome="No", price=0.50),
        ],
    )
    assert abs(m.price_sum - 0.95) < 1e-9


def test_market_spread():
    m = Market(
        condition_id="abc",
        question="Test?",
        slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=0.45),
            Token(token_id="t2", outcome="No", price=0.50),
        ],
    )
    assert abs(m.spread - 0.05) < 1e-9


def test_market_token_ids():
    m = Market(
        condition_id="abc",
        question="Test?",
        slug="test",
        tokens=[
            Token(token_id="yes_id_123", outcome="Yes", price=0.6),
            Token(token_id="no_id_456", outcome="No", price=0.4),
        ],
    )
    assert m.yes_token_id == "yes_id_123"
    assert m.no_token_id == "no_id_456"


def test_market_empty_tokens():
    m = Market(condition_id="abc", question="Test?", slug="test")
    assert m.yes_price == 0.0
    assert m.no_price == 0.0
    assert m.price_sum == 0.0
    assert m.yes_token_id is None
    assert m.no_token_id is None


def test_arbitrage_opportunity_description():
    m = Market(
        condition_id="abc",
        question="Will something happen? This is a longer question to test truncation",
        slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=0.45),
            Token(token_id="t2", outcome="No", price=0.50),
        ],
    )
    opp = ArbitrageOpportunity(
        market=m,
        price_sum=0.95,
        profit_pct=5.0,
        buy_yes_price=0.45,
        buy_no_price=0.50,
        guaranteed_profit=0.05,
        liquidity_score=0.5,
    )
    assert "ARB" in opp.description
    assert "5.00%" in opp.description


def test_trading_signal_description():
    m = Market(
        condition_id="abc",
        question="Will something happen? Yes or no?",
        slug="test",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=0.55),
            Token(token_id="t2", outcome="No", price=0.40),
        ],
    )
    sig = TradingSignal(
        signal_type=SignalType.UNDERVALUED,
        strength=SignalStrength.STRONG,
        market=m,
        confidence=0.85,
        recommended_side="YES",
        recommended_price=0.55,
        expected_value=0.05,
        reason="Test reason",
    )
    assert "UNDERVALUED" in sig.description
    assert "YES" in sig.description
    assert "85%" in sig.description


# ── parse_json_field Tests ────────────────────────────────────────

def test_parse_json_field_none():
    assert parse_json_field(None) == []


def test_parse_json_field_list():
    assert parse_json_field(["a", "b"]) == ["a", "b"]


def test_parse_json_field_json_string():
    assert parse_json_field('["Yes", "No"]') == ["Yes", "No"]


def test_parse_json_field_invalid_string():
    assert parse_json_field("not json") == []


def test_parse_json_field_non_list_json():
    assert parse_json_field('{"key": "value"}') == []
