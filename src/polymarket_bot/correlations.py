"""Cross-market correlation analysis.

Finds related markets with price divergences — opportunities where
correlated outcomes have inconsistent pricing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from polymarket_bot.models import Market


@dataclass
class CorrelatedPair:
    market_a: Market
    market_b: Market
    correlation_type: str
    price_divergence: float
    expected_relationship: str
    reasoning: str
    profit_opportunity: float

    @property
    def description(self) -> str:
        return (
            f"[CORR] {self.market_a.question[:30]}... ↔ "
            f"{self.market_b.question[:30]}... | "
            f"Divergence: {self.price_divergence:.1%} | "
            f"Type: {self.correlation_type}"
        )


@dataclass
class EventCluster:
    theme: str
    markets: list[Market] = field(default_factory=list)
    price_inconsistencies: list[str] = field(default_factory=list)
    total_divergence: float = 0.0


# ── Keywords for topic clustering ──────────────────────────────────

TOPIC_PATTERNS: dict[str, list[str]] = {
    "fed_rates": [
        r"fed\b.*rate", r"interest rate", r"fomc",
        r"federal reserve", r"rate cut", r"rate hike",
    ],
    "bitcoin": [
        r"bitcoin", r"\bbtc\b", r"bitcoin.*\$\d+",
    ],
    "ethereum": [
        r"ethereum", r"\beth\b", r"ethereum.*\$\d+",
    ],
    "us_election": [
        r"president.*202[4-9]", r"election.*202[4-9]",
        r"republican.*nomin", r"democrat.*nomin",
    ],
    "iran": [
        r"\biran\b", r"iranian", r"ceasefire.*iran",
        r"iran.*nuclear", r"iran.*deal",
    ],
    "ukraine": [
        r"\bukraine\b", r"ukrainian", r"zelensky",
        r"ukraine.*ceasefire", r"ukraine.*peace",
    ],
    "ai_tech": [
        r"\bai\b.*model", r"openai", r"chatgpt", r"gpt-\d",
        r"artificial intelligence", r"agi\b",
    ],
    "recession": [
        r"recession", r"\bgdp\b.*contract", r"economic.*downturn",
    ],
    "inflation": [
        r"inflation", r"\bcpi\b", r"consumer price",
    ],
}


class CorrelationAnalyzer:
    """Analyzes cross-market correlations to find price divergences."""

    def __init__(self) -> None:
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {
            topic: [re.compile(p, re.IGNORECASE) for p in patterns]
            for topic, patterns in TOPIC_PATTERNS.items()
        }

    def find_correlations(
        self, markets: list[Market],
    ) -> list[CorrelatedPair]:
        clusters = self._cluster_by_topic(markets)
        pairs: list[CorrelatedPair] = []

        for cluster in clusters.values():
            if len(cluster.markets) < 2:
                continue
            cluster_pairs = self._find_divergences_in_cluster(cluster)
            pairs.extend(cluster_pairs)

        conditional = self._find_conditional_relationships(markets)
        pairs.extend(conditional)

        pairs.sort(key=lambda p: p.profit_opportunity, reverse=True)
        return pairs

    def find_event_clusters(
        self, markets: list[Market],
    ) -> list[EventCluster]:
        clusters = self._cluster_by_topic(markets)
        result: list[EventCluster] = []

        for theme, cluster in clusters.items():
            if len(cluster.markets) >= 2:
                self._analyze_cluster_consistency(cluster)
                result.append(cluster)

        result.sort(key=lambda c: c.total_divergence, reverse=True)
        return result

    def _cluster_by_topic(
        self, markets: list[Market],
    ) -> dict[str, EventCluster]:
        clusters: dict[str, EventCluster] = {}

        for market in markets:
            q = market.question.lower()
            for topic, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    if pattern.search(q):
                        if topic not in clusters:
                            clusters[topic] = EventCluster(theme=topic)
                        clusters[topic].markets.append(market)
                        break

        return clusters

    def _find_divergences_in_cluster(
        self, cluster: EventCluster,
    ) -> list[CorrelatedPair]:
        pairs: list[CorrelatedPair] = []
        markets = cluster.markets

        for i in range(len(markets)):
            for j in range(i + 1, len(markets)):
                pair = self._check_pair(markets[i], markets[j], cluster.theme)
                if pair is not None:
                    pairs.append(pair)

        return pairs

    def _check_pair(
        self, a: Market, b: Market, theme: str,
    ) -> CorrelatedPair | None:
        a_yes = a.yes_price
        b_yes = b.yes_price
        if a_yes <= 0 or b_yes <= 0:
            return None

        # Check timeline relationships (e.g., "Bitcoin $100k by June"
        # should be <= "Bitcoin $100k by December")
        timeline_pair = self._check_timeline_inconsistency(a, b)
        if timeline_pair is not None:
            return timeline_pair

        # Check threshold relationships (e.g., "Bitcoin $100k"
        # should be >= "Bitcoin $150k")
        threshold_pair = self._check_threshold_inconsistency(a, b)
        if threshold_pair is not None:
            return threshold_pair

        return None

    def _check_timeline_inconsistency(
        self, a: Market, b: Market,
    ) -> CorrelatedPair | None:
        """Earlier deadline should have <= probability of later deadline."""
        a_q = a.question.lower()
        b_q = b.question.lower()

        a_core = self._extract_core_question(a_q)
        b_core = self._extract_core_question(b_q)

        if not a_core or not b_core:
            return None
        if a_core != b_core:
            return None

        a_date = self._extract_date_order(a_q)
        b_date = self._extract_date_order(b_q)
        if a_date is None or b_date is None or a_date == b_date:
            return None

        if a_date < b_date:
            earlier, later = a, b
        else:
            earlier, later = b, a

        if earlier.yes_price > later.yes_price + 0.02:
            divergence = earlier.yes_price - later.yes_price
            return CorrelatedPair(
                market_a=earlier,
                market_b=later,
                correlation_type="TIMELINE",
                price_divergence=divergence,
                expected_relationship="earlier ≤ later",
                reasoning=(
                    f"Earlier deadline priced at {earlier.yes_price:.1%} "
                    f"but later at {later.yes_price:.1%} — inconsistent"
                ),
                profit_opportunity=divergence,
            )

        return None

    def _check_threshold_inconsistency(
        self, a: Market, b: Market,
    ) -> CorrelatedPair | None:
        """Higher threshold should have <= probability of lower threshold."""
        a_nums = self._extract_numbers(a.question)
        b_nums = self._extract_numbers(b.question)
        if not a_nums or not b_nums:
            return None

        a_core = self._strip_numbers(a.question.lower())
        b_core = self._strip_numbers(b.question.lower())

        if self._similarity(a_core, b_core) < 0.5:
            return None

        a_val = max(a_nums)
        b_val = max(b_nums)
        if a_val == b_val:
            return None

        if a_val > b_val:
            higher, lower = a, b
            h_val, l_val = a_val, b_val
        else:
            higher, lower = b, a
            h_val, l_val = b_val, a_val

        if higher.yes_price > lower.yes_price + 0.02:
            divergence = higher.yes_price - lower.yes_price
            return CorrelatedPair(
                market_a=higher,
                market_b=lower,
                correlation_type="THRESHOLD",
                price_divergence=divergence,
                expected_relationship=f"${h_val:,.0f} target ≤ ${l_val:,.0f} target",
                reasoning=(
                    f"Higher target (${h_val:,.0f}) at {higher.yes_price:.1%} "
                    f"but lower target (${l_val:,.0f}) at {lower.yes_price:.1%}"
                ),
                profit_opportunity=divergence,
            )

        return None

    def _find_conditional_relationships(
        self, markets: list[Market],
    ) -> list[CorrelatedPair]:
        """Find markets where one outcome implies another."""
        pairs: list[CorrelatedPair] = []


        for m in markets:
            q = m.question.lower()
            if "if" in q or "given" in q or "conditional" in q:
                for other in markets:
                    if other.slug == m.slug:
                        continue
                    if self._is_condition_of(m, other):
                        div = abs(m.yes_price - other.yes_price)
                        if div > 0.05:
                            pairs.append(CorrelatedPair(
                                market_a=m,
                                market_b=other,
                                correlation_type="CONDITIONAL",
                                price_divergence=div,
                                expected_relationship="conditional ≤ unconditional",
                                reasoning=(
                                    f"Conditional market at {m.yes_price:.1%} "
                                    f"vs base at {other.yes_price:.1%}"
                                ),
                                profit_opportunity=div * 0.5,
                            ))

        return pairs

    def _analyze_cluster_consistency(self, cluster: EventCluster) -> None:
        """Check pricing consistency within a cluster."""
        prices = [m.yes_price for m in cluster.markets if m.yes_price > 0]
        if len(prices) < 2:
            return
        avg = sum(prices) / len(prices)
        for m in cluster.markets:
            if m.yes_price > 0:
                dev = abs(m.yes_price - avg) / avg
                if dev > 0.3:
                    cluster.price_inconsistencies.append(
                        f"{m.question[:40]}: {m.yes_price:.1%} vs avg {avg:.1%}"
                    )
                    cluster.total_divergence += dev

    def _is_condition_of(self, conditional: Market, base: Market) -> bool:
        c_words = set(conditional.question.lower().split())
        b_words = set(base.question.lower().split())
        common = c_words & b_words
        stopwords = {"will", "the", "a", "an", "by", "in", "on", "of", "to", "?"}
        meaningful = common - stopwords
        return len(meaningful) >= 3

    def _extract_core_question(self, question: str) -> str:
        q = re.sub(r"by\s+(january|february|march|april|may|june|july|"
                   r"august|september|october|november|december)"
                   r"\s*\d*,?\s*\d*", "", question)
        q = re.sub(r"by\s+\w+\s+\d+", "", q)
        q = re.sub(r"before\s+\w+\s+\d+", "", q)
        q = re.sub(r"\d{4}", "", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _extract_date_order(self, question: str) -> int | None:
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        for month, num in months.items():
            if month in question:
                year_match = re.search(r"(202\d)", question)
                year = int(year_match.group(1)) if year_match else 2026
                return year * 100 + num
        return None

    def _extract_numbers(self, text: str) -> list[float]:
        nums = re.findall(r"\$?([\d,]+(?:\.\d+)?)[kKmM]?", text)
        result: list[float] = []
        for n in nums:
            try:
                val = float(n.replace(",", ""))
                if val > 10:
                    result.append(val)
            except ValueError:
                pass
        return result

    def _strip_numbers(self, text: str) -> str:
        return re.sub(r"\$?[\d,]+(?:\.\d+)?[kKmM]?", "", text).strip()

    def _similarity(self, a: str, b: str) -> float:
        a_words = set(a.split())
        b_words = set(b.split())
        if not a_words or not b_words:
            return 0.0
        common = a_words & b_words
        return len(common) / max(len(a_words), len(b_words))
