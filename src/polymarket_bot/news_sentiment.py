"""News Sentiment Scanner — detects breaking news before market price adjusts.

Uses Google News RSS (free, no API key) to find recent news matching
market topics. When fresh news (<24h) exists but the market price
hasn't reacted yet = potential edge for early positioning.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)

NEWS_RSS_URL = "https://news.google.com/rss/search"


@dataclass
class NewsMatch:
    market_slug: str
    question: str
    headline: str
    source: str
    published: datetime
    hours_ago: float
    relevance_score: float
    current_yes_price: float
    sentiment: str  # POSITIVE, NEGATIVE, NEUTRAL
    recommended_action: str
    confidence: float

    @property
    def description(self) -> str:
        return (
            f"[NEWS] {self.question[:35]} | "
            f"'{self.headline[:40]}' ({self.source}) | "
            f"{self.hours_ago:.0f}h ago | "
            f"Sentiment: {self.sentiment} | {self.recommended_action}"
        )


class NewsSentimentScanner:
    """Scans news for events that could move Polymarket prices."""

    def __init__(self, max_age_hours: float = 48.0) -> None:
        self.max_age_hours = max_age_hours
        self._http = httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._http.close()

    def scan_markets(
        self,
        markets: list[Market],
        max_scan: int = 20,
    ) -> list[NewsMatch]:
        """Find news matches for active markets."""
        matches: list[NewsMatch] = []

        sorted_markets = sorted(
            markets, key=lambda m: m.volume_24h, reverse=True,
        )

        for market in sorted_markets[:max_scan]:
            if not market.active or market.closed:
                continue

            keywords = self._extract_keywords(market.question)
            if not keywords:
                continue

            articles = self._fetch_news(keywords)
            for article in articles[:3]:
                match = self._evaluate_match(market, article)
                if match:
                    matches.append(match)

        matches.sort(key=lambda m: m.relevance_score, reverse=True)
        return matches

    def _extract_keywords(self, question: str) -> str:
        """Extract search keywords from market question."""
        q = question.lower()
        q = re.sub(r"^(will|does|is|has|can|should)\s+", "", q)
        q = re.sub(r"\?$", "", q)
        q = re.sub(
            r"\b(the|a|an|in|on|at|by|for|of|to|be|before|after|this|that)\b",
            "",
            q,
        )
        q = re.sub(r"\s+", " ", q).strip()

        words = q.split()
        if len(words) > 6:
            words = words[:6]
        return " ".join(words)

    def _fetch_news(self, query: str) -> list[dict]:
        """Fetch news articles from Google News RSS."""
        try:
            resp = self._http.get(
                NEWS_RSS_URL,
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            )
            resp.raise_for_status()
            return self._parse_rss(resp.text)
        except Exception as e:
            logger.debug("News fetch failed for '%s': %s", query, e)
            return []

    def _parse_rss(self, xml_text: str) -> list[dict]:
        """Parse RSS XML into article dicts."""
        articles: list[dict] = []
        try:
            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return []

            now = datetime.now(tz=timezone.utc)

            for item in channel.findall("item"):
                title = item.findtext("title", "")
                source_el = item.find("source")
                source = source_el.text if source_el is not None and source_el.text else ""
                pub_date_str = item.findtext("pubDate", "")

                try:
                    pub_date = parsedate_to_datetime(pub_date_str)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pub_date = now

                hours_ago = (now - pub_date).total_seconds() / 3600
                if hours_ago > self.max_age_hours:
                    continue

                articles.append({
                    "title": title,
                    "source": source,
                    "published": pub_date,
                    "hours_ago": hours_ago,
                })

        except ET.ParseError:
            logger.debug("Failed to parse RSS XML")

        return articles

    def _evaluate_match(
        self,
        market: Market,
        article: dict,
    ) -> NewsMatch | None:
        """Evaluate if a news article is relevant and actionable."""
        headline = article["title"]
        relevance = self._relevance_score(market.question, headline)
        if relevance < 0.3:
            return None

        sentiment = self._simple_sentiment(headline)
        hours_ago = article["hours_ago"]

        recency_bonus = max(0, 1.0 - hours_ago / 24)
        confidence = min(relevance * 0.5 + recency_bonus * 0.3, 0.85)

        action = self._recommend_action(
            sentiment, market.yes_price, hours_ago,
        )

        return NewsMatch(
            market_slug=market.slug,
            question=market.question,
            headline=headline,
            source=article["source"],
            published=article["published"],
            hours_ago=round(hours_ago, 1),
            relevance_score=round(relevance, 2),
            current_yes_price=market.yes_price,
            sentiment=sentiment,
            recommended_action=action,
            confidence=round(confidence, 2),
        )

    def _relevance_score(self, question: str, headline: str) -> float:
        """Calculate how relevant a headline is to a market question."""
        q_words = set(question.lower().split())
        h_words = set(headline.lower().split())

        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "will", "would", "could", "should", "may", "might", "can",
            "in", "on", "at", "by", "for", "of", "to", "from", "with",
            "and", "or", "but", "not", "no", "yes", "this", "that",
        }
        q_meaningful = q_words - stop_words
        h_meaningful = h_words - stop_words

        if not q_meaningful:
            return 0.0

        overlap = q_meaningful & h_meaningful
        return len(overlap) / len(q_meaningful)

    def _simple_sentiment(self, headline: str) -> str:
        """Basic sentiment from headline keywords."""
        h = headline.lower()
        pos = ["wins", "gains", "rises", "surges", "approves", "passes",
               "agrees", "deal", "success", "record", "breakthrough"]
        neg = ["falls", "drops", "crashes", "fails", "rejects", "denies",
               "cancels", "delays", "warns", "crisis", "collapse"]

        pos_count = sum(1 for w in pos if w in h)
        neg_count = sum(1 for w in neg if w in h)

        if pos_count > neg_count:
            return "POSITIVE"
        if neg_count > pos_count:
            return "NEGATIVE"
        return "NEUTRAL"

    def _recommend_action(
        self, sentiment: str, price: float, hours_ago: float,
    ) -> str:
        freshness = "FRESH" if hours_ago < 6 else "RECENT"
        if sentiment == "POSITIVE" and price < 0.7:
            return f"BUY YES — {freshness} positive news, price may rise"
        if sentiment == "NEGATIVE" and price > 0.3:
            return f"BUY NO — {freshness} negative news, price may drop"
        return f"WATCH — {freshness} news, sentiment {sentiment.lower()}"
