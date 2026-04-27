"""Tests for correlation analyzer."""

from polymarket_bot.correlations import CorrelationAnalyzer
from polymarket_bot.models import Market, Token


def _make_market(
    question: str, yes_price: float, no_price: float = 0.0, **kwargs,
) -> Market:
    if no_price == 0.0:
        no_price = 1.0 - yes_price
    defaults = {
        "condition_id": "test",
        "slug": question.lower().replace(" ", "-")[:30],
        "volume": 100000,
        "volume_24h": 5000,
    }
    defaults.update(kwargs)
    return Market(
        question=question,
        **defaults,
        tokens=[
            Token(token_id="yes_token", outcome="Yes", price=yes_price),
            Token(token_id="no_token", outcome="No", price=no_price),
        ],
    )


def test_clusters_related_markets():
    analyzer = CorrelationAnalyzer()
    markets = [
        _make_market("Will Bitcoin hit $100k by June?", 0.6, slug="btc-100k"),
        _make_market("Will Bitcoin hit $150k by June?", 0.3, slug="btc-150k"),
        _make_market("Will the Fed cut rates?", 0.7, slug="fed-cut"),
    ]
    clusters = analyzer.find_event_clusters(markets)
    bitcoin_cluster = [c for c in clusters if c.theme == "bitcoin"]
    assert len(bitcoin_cluster) == 1
    assert len(bitcoin_cluster[0].markets) == 2


def test_finds_threshold_inconsistency():
    analyzer = CorrelationAnalyzer()
    markets = [
        _make_market("Will Bitcoin hit $100k?", 0.4, slug="btc-100k"),
        _make_market("Will Bitcoin hit $150k?", 0.6, slug="btc-150k"),
    ]
    pairs = analyzer.find_correlations(markets)
    threshold_pairs = [p for p in pairs if p.correlation_type == "THRESHOLD"]
    assert len(threshold_pairs) >= 1
    assert threshold_pairs[0].price_divergence > 0


def test_no_divergence_for_consistent_prices():
    analyzer = CorrelationAnalyzer()
    markets = [
        _make_market("Will Bitcoin hit $100k?", 0.6, slug="btc-100k"),
        _make_market("Will Bitcoin hit $150k?", 0.3, slug="btc-150k"),
    ]
    pairs = analyzer.find_correlations(markets)
    threshold_pairs = [p for p in pairs if p.correlation_type == "THRESHOLD"]
    assert len(threshold_pairs) == 0


def test_unrelated_markets_no_pairs():
    analyzer = CorrelationAnalyzer()
    markets = [
        _make_market("Will it rain tomorrow?", 0.5, slug="rain"),
        _make_market("Who wins the NBA finals?", 0.3, slug="nba"),
    ]
    pairs = analyzer.find_correlations(markets)
    assert len(pairs) == 0


def test_timeline_inconsistency():
    analyzer = CorrelationAnalyzer()
    markets = [
        _make_market("Will Bitcoin hit $100k by June?", 0.7, slug="btc-100k-jun"),
        _make_market("Will Bitcoin hit $100k by December?", 0.5, slug="btc-100k-dec"),
    ]
    pairs = analyzer.find_correlations(markets)
    timeline_pairs = [p for p in pairs if p.correlation_type == "TIMELINE"]
    assert len(timeline_pairs) >= 1


def test_empty_markets_no_crash():
    analyzer = CorrelationAnalyzer()
    pairs = analyzer.find_correlations([])
    clusters = analyzer.find_event_clusters([])
    assert pairs == []
    assert clusters == []


def test_single_market_no_cluster():
    analyzer = CorrelationAnalyzer()
    markets = [_make_market("Will Bitcoin hit $100k?", 0.5, slug="btc-100k")]
    clusters = analyzer.find_event_clusters(markets)
    assert len(clusters) == 0


def test_number_extraction_with_k_suffix():
    analyzer = CorrelationAnalyzer()
    nums = analyzer._extract_numbers("Will BTC hit $100k?")
    assert 100000 in nums
