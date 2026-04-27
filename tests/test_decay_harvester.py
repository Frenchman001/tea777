"""Tests for decay harvester module."""

from datetime import datetime, timedelta, timezone

from polymarket_bot.decay_harvester import DecayHarvester, DecayOpportunity, _guess_simple_category
from polymarket_bot.models import Market, Token


def _make_market(
    yes_price: float = 0.03,
    days_ahead: float = 5.0,
    volume: float = 10000,
    liq: float = 50000,
) -> Market:
    end = datetime.now(tz=timezone.utc) + timedelta(days=days_ahead)
    return Market(
        condition_id="c1", question="Will Bitcoin hit $200k?", slug="btc-200k",
        tokens=[
            Token(token_id="t1", outcome="Yes", price=yes_price),
            Token(token_id="t2", outcome="No", price=1 - yes_price),
        ],
        volume_24h=volume,
        liquidity=liq,
        end_date=end.isoformat(),
    )


def test_decay_opportunity_description():
    opp = DecayOpportunity(
        market_slug="test", question="Will X happen?",
        yes_price=0.03, no_price=0.97,
        days_to_expiry=5, annualized_return_pct=200,
        profit_per_dollar=0.031, recommended_bet_usd=50,
        recommended_side="BUY_NO", risk_level="LOW",
        category="crypto", confidence=0.8,
    )
    assert "DECAY" in opp.description
    assert "200%/yr" in opp.description


def test_scan_finds_low_yes():
    harvester = DecayHarvester(max_yes_price=0.08, max_days=14)
    markets = [_make_market(yes_price=0.03, days_ahead=5)]
    opps = harvester.scan(markets)
    assert len(opps) >= 1
    assert opps[0].recommended_side == "BUY_NO"
    assert opps[0].annualized_return_pct > 0


def test_scan_skips_high_yes():
    harvester = DecayHarvester(max_yes_price=0.08)
    markets = [_make_market(yes_price=0.50, days_ahead=5)]
    opps = harvester.scan(markets)
    assert len(opps) == 0


def test_scan_skips_too_far():
    harvester = DecayHarvester(max_days=7)
    markets = [_make_market(yes_price=0.03, days_ahead=30)]
    opps = harvester.scan(markets)
    assert len(opps) == 0


def test_scan_skips_no_end_date():
    harvester = DecayHarvester()
    m = Market(
        condition_id="c1", question="No end date", slug="no-end",
        tokens=[Token(token_id="t1", outcome="Yes", price=0.03)],
    )
    opps = harvester.scan([m])
    assert len(opps) == 0


def test_risk_assessment():
    harvester = DecayHarvester()
    assert harvester._assess_risk(0.01, 2, 10000) == "LOW"
    assert harvester._assess_risk(0.04, 5, 5000) == "MEDIUM"
    assert harvester._assess_risk(0.07, 12, 1000) == "HIGH"


def test_guess_category():
    assert _guess_simple_category("Will Bitcoin hit $100k?") == "crypto"
    assert _guess_simple_category("Will Lakers win NBA?") == "sports"
    assert _guess_simple_category("Will Trump win election?") == "politics"
    assert _guess_simple_category("Will it rain?") == "other"
