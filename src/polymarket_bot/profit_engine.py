"""Advanced profit maximization engine.

Includes Kelly Criterion bet sizing, fee-aware ROI calculation,
orderbook depth analysis, and composite market scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from polymarket_bot.models import Market, OrderBook

# ── Polymarket Fee Schedule (2026) ─────────────────────────────────

FEE_SCHEDULE: dict[str, tuple[float, float]] = {
    # category -> (fee_rate, exponent)
    "crypto": (0.072, 1.0),
    "sports": (0.030, 1.0),
    "finance": (0.040, 1.0),
    "politics": (0.040, 1.0),
    "tech": (0.040, 1.0),
    "economics": (0.030, 0.5),
    "culture": (0.050, 1.0),
    "weather": (0.025, 0.5),
    "other": (0.200, 2.0),
    "mentions": (0.250, 2.0),
    "geopolitics": (0.0, 1.0),
}

DEFAULT_FEE = (0.040, 1.0)


class RiskTier(str, Enum):
    ULTRA_LOW = "ULTRA_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass
class FeeEstimate:
    fee_rate: float
    exponent: float
    price: float
    shares: float
    fee_amount: float
    effective_fee_pct: float
    category: str


@dataclass
class SlippageEstimate:
    avg_fill_price: float
    worst_fill_price: float
    slippage_pct: float
    fillable_amount: float
    levels_consumed: int


@dataclass
class BetSizing:
    kelly_fraction: float
    kelly_bet_usd: float
    half_kelly_bet_usd: float
    quarter_kelly_bet_usd: float
    recommended_bet_usd: float
    edge: float
    win_probability: float
    bankroll: float


@dataclass
class MarketScore:
    market: Market
    total_score: float
    ev_score: float
    liquidity_score: float
    time_score: float
    volume_score: float
    risk_tier: RiskTier
    expected_profit_usd: float
    fee_adjusted_ev: float
    recommended_bet: float
    reasoning: list[str] = field(default_factory=list)


# ── Fee Calculator ─────────────────────────────────────────────────

def calculate_fee(
    price: float,
    shares: float,
    category: str = "other",
) -> FeeEstimate:
    """Calculate Polymarket taker fee using the probability-based formula.

    fee = shares * price * fee_rate * (price * (1 - price)) ^ exponent
    """
    fee_rate, exponent = FEE_SCHEDULE.get(category.lower(), DEFAULT_FEE)

    if fee_rate == 0 or price <= 0 or price >= 1 or shares <= 0:
        return FeeEstimate(
            fee_rate=fee_rate, exponent=exponent, price=price,
            shares=shares, fee_amount=0.0, effective_fee_pct=0.0,
            category=category,
        )

    prob_factor = (price * (1.0 - price)) ** exponent
    fee_amount = shares * price * fee_rate * prob_factor
    cost = shares * price
    effective_pct = (fee_amount / cost * 100) if cost > 0 else 0.0

    return FeeEstimate(
        fee_rate=fee_rate, exponent=exponent, price=price,
        shares=shares, fee_amount=fee_amount,
        effective_fee_pct=effective_pct, category=category,
    )


def calculate_net_profit(
    buy_price: float,
    shares: float,
    win_probability: float,
    category: str = "other",
) -> float:
    """Calculate expected net profit after fees."""
    cost = shares * buy_price
    fee = calculate_fee(buy_price, shares, category)
    total_cost = cost + fee.fee_amount

    expected_payout = shares * win_probability
    return expected_payout - total_cost


# ── Kelly Criterion ────────────────────────────────────────────────

def kelly_criterion(
    win_probability: float,
    price: float,
    bankroll: float = 1000.0,
    max_fraction: float = 0.25,
    category: str = "other",
) -> BetSizing:
    """Calculate optimal bet size using Kelly Criterion.

    Kelly formula: f* = (p * b - q) / b
    where p = win probability, q = 1 - p, b = net odds (payout / stake - 1)

    Adjusted for Polymarket fees.
    """
    if price <= 0 or price >= 1 or win_probability <= 0:
        return BetSizing(
            kelly_fraction=0.0, kelly_bet_usd=0.0,
            half_kelly_bet_usd=0.0, quarter_kelly_bet_usd=0.0,
            recommended_bet_usd=0.0, edge=0.0,
            win_probability=win_probability, bankroll=bankroll,
        )

    fee_est = calculate_fee(price, 1.0, category)
    effective_price = price * (1.0 + fee_est.effective_fee_pct / 100.0)

    if effective_price >= 1.0:
        return BetSizing(
            kelly_fraction=0.0, kelly_bet_usd=0.0,
            half_kelly_bet_usd=0.0, quarter_kelly_bet_usd=0.0,
            recommended_bet_usd=0.0, edge=0.0,
            win_probability=win_probability, bankroll=bankroll,
        )

    b = (1.0 / effective_price) - 1.0
    q = 1.0 - win_probability

    kelly_f = (win_probability * b - q) / b if b > 0 else 0.0
    kelly_f = max(kelly_f, 0.0)
    kelly_f = min(kelly_f, max_fraction)

    edge = win_probability - effective_price

    kelly_bet = kelly_f * bankroll
    half_kelly = kelly_bet * 0.5
    quarter_kelly = kelly_bet * 0.25

    recommended = half_kelly

    return BetSizing(
        kelly_fraction=kelly_f,
        kelly_bet_usd=round(kelly_bet, 2),
        half_kelly_bet_usd=round(half_kelly, 2),
        quarter_kelly_bet_usd=round(quarter_kelly, 2),
        recommended_bet_usd=round(recommended, 2),
        edge=round(edge, 4),
        win_probability=win_probability,
        bankroll=bankroll,
    )


# ── Orderbook Depth / Slippage ─────────────────────────────────────

def estimate_slippage(
    orderbook: OrderBook,
    order_size_usd: float,
    side: str = "buy",
) -> SlippageEstimate:
    """Estimate slippage for a given order size using orderbook depth."""
    levels = orderbook.asks if side == "buy" else orderbook.bids

    if not levels:
        return SlippageEstimate(
            avg_fill_price=0.0, worst_fill_price=0.0,
            slippage_pct=0.0, fillable_amount=0.0,
            levels_consumed=0,
        )

    remaining = order_size_usd
    total_cost = 0.0
    total_shares = 0.0
    levels_consumed = 0
    worst_price = levels[0].price

    for level in levels:
        level_value = level.price * level.size
        if level_value >= remaining:
            shares_from_level = remaining / level.price
            total_shares += shares_from_level
            total_cost += remaining
            worst_price = level.price
            levels_consumed += 1
            remaining = 0
            break
        else:
            total_shares += level.size
            total_cost += level_value
            worst_price = level.price
            levels_consumed += 1
            remaining -= level_value

    fillable = order_size_usd - remaining
    avg_price = total_cost / total_shares if total_shares > 0 else 0.0
    best_price = levels[0].price
    slippage = ((avg_price - best_price) / best_price * 100) if best_price > 0 else 0.0

    if side == "sell":
        slippage = ((best_price - avg_price) / best_price * 100) if best_price > 0 else 0.0

    return SlippageEstimate(
        avg_fill_price=round(avg_price, 6),
        worst_fill_price=round(worst_price, 6),
        slippage_pct=round(abs(slippage), 4),
        fillable_amount=round(fillable, 2),
        levels_consumed=levels_consumed,
    )


# ── Market Scoring ─────────────────────────────────────────────────

def score_market(
    market: Market,
    estimated_true_prob: float | None = None,
    bankroll: float = 1000.0,
    orderbook: OrderBook | None = None,
) -> MarketScore:
    """Score a market for profit potential using composite factors.

    Components:
    - EV score: expected value based on mispricing
    - Liquidity score: ability to execute trades
    - Time score: time decay and urgency
    - Volume score: market activity and reliability
    """
    reasoning: list[str] = []

    yes_price = market.yes_price
    no_price = market.no_price
    if estimated_true_prob is None:
        estimated_true_prob = yes_price

    # ── EV Score (0-10) ──
    edge_yes = estimated_true_prob - yes_price
    edge_no = (1.0 - estimated_true_prob) - no_price

    best_edge = max(edge_yes, edge_no)
    best_side_price = yes_price if edge_yes >= edge_no else no_price

    category = _guess_category(market)
    fee = calculate_fee(best_side_price, 1.0, category)
    fee_adjusted_edge = best_edge - (fee.effective_fee_pct / 100.0)

    ev_score = max(fee_adjusted_edge * 50.0, 0.0)
    ev_score = min(ev_score, 10.0)

    if fee_adjusted_edge > 0.05:
        reasoning.append(f"Strong edge: {fee_adjusted_edge:.1%} after fees")
    elif fee_adjusted_edge > 0.02:
        reasoning.append(f"Moderate edge: {fee_adjusted_edge:.1%} after fees")

    # ── Liquidity Score (0-10) ──
    liq = market.liquidity
    if liq >= 100000:
        liquidity_score = 10.0
    elif liq >= 10000:
        liquidity_score = 5.0 + (liq - 10000) / 18000.0
    elif liq >= 1000:
        liquidity_score = 2.0 + (liq - 1000) / 3000.0
    else:
        liquidity_score = liq / 500.0

    if orderbook:
        slip = estimate_slippage(orderbook, 100.0)
        if slip.slippage_pct < 0.5:
            liquidity_score = min(liquidity_score + 2.0, 10.0)
            reasoning.append("Tight orderbook — low slippage")
        elif slip.slippage_pct > 3.0:
            liquidity_score = max(liquidity_score - 2.0, 0.0)
            reasoning.append(f"High slippage: {slip.slippage_pct:.1f}%")

    # ── Time Score (0-10) ──
    time_score = 5.0
    if market.end_date:
        try:
            end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
            days_left = (end - datetime.now(tz=timezone.utc)).days
            if days_left < 1:
                time_score = 9.0
                reasoning.append("Resolves today — urgent")
            elif days_left < 7:
                time_score = 7.0
                reasoning.append(f"Resolves in {days_left} days")
            elif days_left < 30:
                time_score = 5.0
            elif days_left < 90:
                time_score = 3.0
            else:
                time_score = 1.5
                reasoning.append("Long-dated market — capital locked")
        except (ValueError, TypeError):
            pass

    # ── Volume Score (0-10) ──
    vol_24h = market.volume_24h
    if vol_24h >= 500000:
        volume_score = 10.0
    elif vol_24h >= 50000:
        volume_score = 5.0 + (vol_24h - 50000) / 90000.0
    elif vol_24h >= 5000:
        volume_score = 2.0 + (vol_24h - 5000) / 15000.0
    elif vol_24h > 0:
        volume_score = vol_24h / 2500.0
    else:
        volume_score = 0.0

    # ── Composite Score ──
    weights = {"ev": 0.40, "liq": 0.20, "time": 0.15, "vol": 0.25}
    total = (
        ev_score * weights["ev"]
        + liquidity_score * weights["liq"]
        + time_score * weights["time"]
        + volume_score * weights["vol"]
    )

    # ── Risk Tier ──
    risk_tier = _assess_risk(market, fee_adjusted_edge, liquidity_score)

    # ── Expected Profit ──
    kelly = kelly_criterion(
        estimated_true_prob, best_side_price,
        bankroll=bankroll, category=category,
    )
    expected_profit = kelly.recommended_bet_usd * fee_adjusted_edge

    return MarketScore(
        market=market,
        total_score=round(total, 2),
        ev_score=round(ev_score, 2),
        liquidity_score=round(liquidity_score, 2),
        time_score=round(time_score, 2),
        volume_score=round(volume_score, 2),
        risk_tier=risk_tier,
        expected_profit_usd=round(expected_profit, 2),
        fee_adjusted_ev=round(fee_adjusted_edge, 4),
        recommended_bet=kelly.recommended_bet_usd,
        reasoning=reasoning,
    )


def _guess_category(market: Market) -> str:
    """Guess market category from tags and question text."""
    tags_lower = [t.lower() for t in market.tags]
    q = market.question.lower()

    category_keywords: dict[str, list[str]] = {
        "crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth", "solana"],
        "sports": [
            "nba", "nfl", "mlb", "soccer", "football", "tennis",
            "fifa", "world cup", "champions league", "premier league",
            "la liga", "serie a", "bundesliga", "ufc", "boxing",
            "f1", "formula 1", "cricket", "hockey", "nhl",
        ],
        "politics": ["election", "president", "senate", "congress", "vote"],
        "finance": ["fed", "interest rate", "gdp", "stock", "s&p"],
        "tech": ["ai", "openai", "google", "apple", "microsoft", "spacex"],
        "geopolitics": ["war", "ceasefire", "iran", "ukraine", "china"],
        "weather": ["hurricane", "temperature", "weather", "climate"],
        "economics": ["inflation", "unemployment", "recession", "cpi"],
    }

    for cat, keywords in category_keywords.items():
        for kw in keywords:
            if kw in q or any(kw in t for t in tags_lower):
                return cat

    return "other"


def _assess_risk(
    market: Market,
    edge: float,
    liquidity_score: float,
) -> RiskTier:
    """Assess risk tier based on market characteristics."""
    if edge > 0.10 and liquidity_score > 7.0:
        return RiskTier.ULTRA_LOW
    if edge > 0.05 and liquidity_score > 5.0:
        return RiskTier.LOW
    if edge > 0.02 and liquidity_score > 3.0:
        return RiskTier.MEDIUM
    if edge > 0 and liquidity_score > 1.0:
        return RiskTier.HIGH
    return RiskTier.EXTREME
