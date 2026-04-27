"""Tests for external data integration."""

from polymarket_bot.external_data import (
    CryptoDataProvider,
    ExternalDataAggregator,
    ExternalSignal,
)
from polymarket_bot.models import Market, Token


def _make_crypto_market(question: str, yes_price: float) -> Market:
    return Market(
        condition_id="c1", question=question, slug="test",
        tokens=[
            Token(token_id="y1", outcome="Yes", price=yes_price),
            Token(token_id="n1", outcome="No", price=1 - yes_price),
        ],
    )


def test_external_signal_has_edge():
    sig = ExternalSignal(
        source="test", market_slug="s", market_question="q",
        polymarket_price=0.5, estimated_probability=0.6,
        edge=0.10, recommended_side="YES", reasoning="test",
    )
    assert sig.has_edge is True


def test_external_signal_no_edge():
    sig = ExternalSignal(
        source="test", market_slug="s", market_question="q",
        polymarket_price=0.5, estimated_probability=0.52,
        edge=0.02, recommended_side="YES", reasoning="test",
    )
    assert sig.has_edge is False


def test_crypto_analyze_no_price_in_question():
    provider = CryptoDataProvider()
    m = _make_crypto_market("Will bitcoin be popular?", 0.8)
    result = provider.analyze_crypto_market(m)
    # No target price in question
    assert result is None
    provider.close()


def test_crypto_analyze_non_crypto():
    provider = CryptoDataProvider()
    m = _make_crypto_market("Will it rain tomorrow? $100", 0.5)
    result = provider.analyze_crypto_market(m)
    assert result is None
    provider.close()


def test_aggregator_with_non_crypto_markets():
    agg = ExternalDataAggregator()
    markets = [
        _make_crypto_market("Will Trump win?", 0.5),
        _make_crypto_market("Rain tomorrow?", 0.3),
    ]
    try:
        signals = agg.analyze_markets(markets)
        assert isinstance(signals, list)
    finally:
        agg.close()
