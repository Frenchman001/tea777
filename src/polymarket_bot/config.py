"""Configuration for Polymarket bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # API endpoints
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137

    # Arbitrage settings
    min_profit_pct: float = 0.5
    max_price_sum: float = 0.995
    min_liquidity: float = 1000.0
    min_volume_24h: float = 500.0

    # Signal settings
    min_confidence: float = 0.6
    max_risk_score: float = 0.7
    strong_signal_threshold: float = 0.8

    # Scanning settings
    scan_interval_sec: int = 30
    max_markets_per_scan: int = 500
    request_delay_sec: float = 0.1

    # Trading settings (optional — requires private key)
    private_key: str | None = None
    funder_address: str | None = None
    max_bet_size_usd: float = 50.0
    auto_trade: bool = False

    # Filters
    exclude_tags: list[str] = field(default_factory=list)
    include_tags: list[str] = field(default_factory=list)
    min_end_days: int = 1

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            clob_host=os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com"),
            gamma_host=os.getenv("POLYMARKET_GAMMA_HOST", "https://gamma-api.polymarket.com"),
            min_profit_pct=float(os.getenv("MIN_PROFIT_PCT", "0.5")),
            max_price_sum=float(os.getenv("MAX_PRICE_SUM", "0.995")),
            min_liquidity=float(os.getenv("MIN_LIQUIDITY", "1000")),
            min_volume_24h=float(os.getenv("MIN_VOLUME_24H", "500")),
            min_confidence=float(os.getenv("MIN_CONFIDENCE", "0.6")),
            scan_interval_sec=int(os.getenv("SCAN_INTERVAL_SEC", "30")),
            max_markets_per_scan=int(os.getenv("MAX_MARKETS_PER_SCAN", "500")),
            private_key=os.getenv("POLYMARKET_PRIVATE_KEY"),
            funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS"),
            max_bet_size_usd=float(os.getenv("MAX_BET_SIZE_USD", "50")),
            auto_trade=os.getenv("AUTO_TRADE", "false").lower() == "true",
        )
