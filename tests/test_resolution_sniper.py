"""Tests for resolution_sniper module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polymarket_bot.models import Market, Token
from polymarket_bot.resolution_sniper import ResolutionSniper, _detect_cat


def _make_market(
    yes: float = 0.97,
    no: float = 0.03,
    slug: str = "test",
    question: str = "Will it happen?",
    hours_until: float = 12.0,
    volume: float = 50000.0,
    liquidity: float = 100000.0,
) -> Market:
    end = datetime.now(tz=timezone.utc) + timedelta(hours=hours_until)
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
        end_date=end.isoformat(),
        volume_24h=volume,
        liquidity=liquidity,
    )


class TestResolutionSniper:
    def test_finds_near_certain_yes(self) -> None:
        sniper = ResolutionSniper(min_certainty=0.93, max_hours=72)
        m = _make_market(yes=0.97, hours_until=12)
        targets = sniper.scan([m])
        assert len(targets) >= 1
        assert targets[0].likely_outcome == "YES"
        assert targets[0].outcome_price >= 0.93
        assert targets[0].net_profit_per_100 > 0

    def test_finds_near_certain_no(self) -> None:
        sniper = ResolutionSniper(min_certainty=0.93, max_hours=72)
        m = _make_market(yes=0.03, no=0.97, hours_until=12)
        targets = sniper.scan([m])
        assert len(targets) >= 1
        assert targets[0].likely_outcome == "NO"

    def test_skips_uncertain_markets(self) -> None:
        sniper = ResolutionSniper(min_certainty=0.93, max_hours=72)
        m = _make_market(yes=0.60, no=0.40, hours_until=12)
        targets = sniper.scan([m])
        assert len(targets) == 0

    def test_skips_far_resolution(self) -> None:
        sniper = ResolutionSniper(min_certainty=0.93, max_hours=72)
        m = _make_market(yes=0.97, hours_until=200)
        targets = sniper.scan([m])
        assert len(targets) == 0

    def test_skips_closed_market(self) -> None:
        sniper = ResolutionSniper(min_certainty=0.93, max_hours=72)
        m = _make_market(yes=0.97, hours_until=12)
        m.closed = True
        targets = sniper.scan([m])
        assert len(targets) == 0

    def test_risk_assessment_low(self) -> None:
        sniper = ResolutionSniper()
        risk = sniper._assess_risk(0.99, 12, 100000)
        assert risk == "LOW"

    def test_risk_assessment_medium(self) -> None:
        sniper = ResolutionSniper()
        risk = sniper._assess_risk(0.96, 36, 20000)
        assert risk == "MEDIUM"

    def test_risk_assessment_high(self) -> None:
        sniper = ResolutionSniper()
        risk = sniper._assess_risk(0.93, 60, 2000)
        assert risk == "HIGH"

    def test_target_description(self) -> None:
        from polymarket_bot.resolution_sniper import SniperTarget
        t = SniperTarget(
            market_slug="test",
            question="Will Bitcoin hit $100k?",
            likely_outcome="YES",
            outcome_price=0.97,
            profit_per_share=0.03,
            hours_to_resolution=12,
            volume_24h=50000,
            liquidity=100000,
            net_profit_per_100=2.5,
            confidence=0.92,
            risk_level="LOW",
            recommended_bet=50,
            category="crypto",
        )
        assert "SNIPER" in t.description
        assert "YES" in t.description

    def test_recommended_bet_within_bankroll(self) -> None:
        sniper = ResolutionSniper(bankroll=1000)
        m = _make_market(yes=0.97, hours_until=12)
        targets = sniper.scan([m])
        if targets:
            assert targets[0].recommended_bet <= 1000


class TestDetectCat:
    def test_crypto(self) -> None:
        assert _detect_cat("Bitcoin price above $100k") == "crypto"

    def test_politics(self) -> None:
        assert _detect_cat("Trump wins election") == "politics"

    def test_other(self) -> None:
        assert _detect_cat("Some random thing") == "other"
