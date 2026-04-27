"""Tests for news sentiment scanner module."""

from polymarket_bot.news_sentiment import NewsSentimentScanner


def test_extract_keywords():
    scanner = NewsSentimentScanner()
    kw = scanner._extract_keywords("Will Bitcoin hit $100k by December?")
    assert "bitcoin" in kw.lower()
    assert "will" not in kw.lower()


def test_extract_keywords_short():
    scanner = NewsSentimentScanner()
    kw = scanner._extract_keywords("Trump wins?")
    assert "trump" in kw.lower()
    assert "wins" in kw.lower()


def test_simple_sentiment_positive():
    scanner = NewsSentimentScanner()
    assert scanner._simple_sentiment("Company wins major deal") == "POSITIVE"
    assert scanner._simple_sentiment("Stock surges to record") == "POSITIVE"


def test_simple_sentiment_negative():
    scanner = NewsSentimentScanner()
    assert scanner._simple_sentiment("Market crashes after crisis") == "NEGATIVE"
    assert scanner._simple_sentiment("Company fails to deliver") == "NEGATIVE"


def test_simple_sentiment_neutral():
    scanner = NewsSentimentScanner()
    assert scanner._simple_sentiment("Company announces plans") == "NEUTRAL"


def test_relevance_score():
    scanner = NewsSentimentScanner()
    score = scanner._relevance_score(
        "Will Bitcoin hit $100k?",
        "Bitcoin reaches new high near $100k",
    )
    assert score > 0.3

    low_score = scanner._relevance_score(
        "Will Bitcoin hit $100k?",
        "New restaurant opens in NYC",
    )
    assert low_score < 0.2


def test_recommend_action():
    scanner = NewsSentimentScanner()
    action = scanner._recommend_action("POSITIVE", 0.3, 2)
    assert "BUY YES" in action
    assert "FRESH" in action

    action = scanner._recommend_action("NEGATIVE", 0.7, 10)
    assert "BUY NO" in action
    assert "RECENT" in action

    action = scanner._recommend_action("NEUTRAL", 0.5, 3)
    assert "WATCH" in action
