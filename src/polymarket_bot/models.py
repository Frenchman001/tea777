"""Data models for Polymarket bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SignalType(str, Enum):
    ARBITRAGE = "ARBITRAGE"
    UNDERVALUED = "UNDERVALUED"
    OVERVALUED = "OVERVALUED"
    MOMENTUM = "MOMENTUM"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


@dataclass
class Token:
    token_id: str
    outcome: str
    price: float
    winner: bool = False


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[Token] = field(default_factory=list)
    volume: float = 0.0
    volume_24h: float = 0.0
    liquidity: float = 0.0
    end_date: str = ""
    active: bool = True
    closed: bool = False
    tags: list[str] = field(default_factory=list)
    description: str = ""
    event_slug: str = ""

    @property
    def yes_price(self) -> float:
        for t in self.tokens:
            if t.outcome.upper() == "YES":
                return t.price
        return 0.0

    @property
    def no_price(self) -> float:
        for t in self.tokens:
            if t.outcome.upper() == "NO":
                return t.price
        return 0.0

    @property
    def price_sum(self) -> float:
        return sum(t.price for t in self.tokens)

    @property
    def spread(self) -> float:
        return abs(1.0 - self.price_sum)

    @property
    def yes_token_id(self) -> str | None:
        for t in self.tokens:
            if t.outcome.upper() == "YES":
                return t.token_id
        return None

    @property
    def no_token_id(self) -> str | None:
        for t in self.tokens:
            if t.outcome.upper() == "NO":
                return t.token_id
        return None


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    midpoint: float = 0.0


@dataclass
class ArbitrageOpportunity:
    market: Market
    price_sum: float
    profit_pct: float
    buy_yes_price: float
    buy_no_price: float
    guaranteed_profit: float
    liquidity_score: float = 0.0

    @property
    def description(self) -> str:
        return (
            f"[ARB] {self.market.question[:60]}... | "
            f"YES={self.buy_yes_price:.3f} + NO={self.buy_no_price:.3f} = {self.price_sum:.3f} | "
            f"Profit: {self.profit_pct:.2f}%"
        )


@dataclass
class TradingSignal:
    signal_type: SignalType
    strength: SignalStrength
    market: Market
    confidence: float
    recommended_side: str
    recommended_price: float
    expected_value: float
    reason: str
    risk_score: float = 0.5

    @property
    def description(self) -> str:
        return (
            f"[{self.signal_type.value}] {self.market.question[:50]}... | "
            f"Side: {self.recommended_side} @ {self.recommended_price:.3f} | "
            f"Confidence: {self.confidence:.0%} | EV: {self.expected_value:+.3f}"
        )
