from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SportType(str, Enum):
    FOOTBALL = "football"
    BASKETBALL = "basketball"
    TENNIS = "tennis"
    HOCKEY = "hockey"
    MMA = "mma"
    BOXING = "boxing"
    ESPORTS = "esports"
    OTHER = "other"


class OutcomeType(str, Enum):
    WIN_HOME = "win_home"
    WIN_AWAY = "win_away"
    DRAW = "draw"
    YES = "yes"
    NO = "no"
    OVER = "over"
    UNDER = "under"


class Outcome(BaseModel):
    name: str
    outcome_type: OutcomeType
    odds: float = Field(ge=1.0, description="Decimal odds (e.g., 2.5 means +150)")
    probability: float = Field(ge=0.0, le=1.0, description="Implied probability")

    @classmethod
    def from_odds(cls, name: str, outcome_type: OutcomeType, odds: float) -> "Outcome":
        return cls(name=name, outcome_type=outcome_type, odds=odds, probability=1.0 / odds)

    @classmethod
    def from_probability(cls, name: str, outcome_type: OutcomeType, prob: float) -> "Outcome":
        odds = 1.0 / prob if prob > 0 else 999.0
        return cls(name=name, outcome_type=outcome_type, odds=odds, probability=prob)


class SportEvent(BaseModel):
    event_id: str
    sport: SportType
    league: str = ""
    home_team: str
    away_team: str
    start_time: datetime | None = None
    description: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.home_team} vs {self.away_team}"


class PolymarketMarket(BaseModel):
    condition_id: str
    question: str
    slug: str = ""
    sport: SportType = SportType.OTHER
    outcomes: list[Outcome] = Field(default_factory=list)
    end_date: datetime | None = None
    volume: float = 0.0
    liquidity: float = 0.0
    active: bool = True
    matched_event: SportEvent | None = None

    @property
    def best_yes_price(self) -> float:
        for o in self.outcomes:
            if o.outcome_type == OutcomeType.YES:
                return o.probability
        return 0.0

    @property
    def best_no_price(self) -> float:
        for o in self.outcomes:
            if o.outcome_type == OutcomeType.NO:
                return o.probability
        return 0.0


class BookmakerOdds(BaseModel):
    bookmaker: str
    event: SportEvent
    outcomes: list[Outcome] = Field(default_factory=list)
    url: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    def get_outcome(self, outcome_type: OutcomeType) -> Outcome | None:
        for o in self.outcomes:
            if o.outcome_type == outcome_type:
                return o
        return None


class ArbitrageOpportunity(BaseModel):
    polymarket_market: PolymarketMarket
    bookmaker_odds: BookmakerOdds
    poly_side: OutcomeType
    bk_side: OutcomeType
    poly_odds: float
    bk_odds: float
    profit_percent: float
    optimal_poly_stake: float = 0.0
    optimal_bk_stake: float = 0.0
    total_stake: float = 0.0
    guaranteed_profit: float = 0.0

    @property
    def display(self) -> str:
        return (
            f"🔥 ARB: {self.polymarket_market.question}\n"
            f"📊 Polymarket [{self.poly_side.value}]: {self.poly_odds:.3f}\n"
            f"🏢 {self.bookmaker_odds.bookmaker} [{self.bk_side.value}]: {self.bk_odds:.3f}\n"
            f"💰 Profit: {self.profit_percent:.2f}%\n"
            f"💵 Stakes: PM=${self.optimal_poly_stake:.2f} + "
            f"BK=${self.optimal_bk_stake:.2f} = ${self.total_stake:.2f}\n"
            f"✅ Guaranteed: ${self.guaranteed_profit:.2f}"
        )
