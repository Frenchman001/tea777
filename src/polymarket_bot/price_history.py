"""Price history storage and trend analysis using SQLite."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from polymarket_bot.models import Market

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".polymarket_bot" / "price_history.db"


@dataclass
class PricePoint:
    slug: str
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    timestamp: float


@dataclass
class TrendAnalysis:
    slug: str
    question: str
    current_price: float
    price_1h_ago: float | None
    price_24h_ago: float | None
    price_7d_ago: float | None
    trend_1h: float
    trend_24h: float
    trend_7d: float
    volatility_24h: float
    volume_trend: float
    support_level: float
    resistance_level: float
    signal: str

    @property
    def is_trending_up(self) -> bool:
        return self.trend_24h > 0.02

    @property
    def is_trending_down(self) -> bool:
        return self.trend_24h < -0.02


class PriceHistoryDB:
    """SQLite-backed price history for trend analysis."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                yes_price REAL NOT NULL,
                no_price REAL NOT NULL,
                volume_24h REAL DEFAULT 0,
                liquidity REAL DEFAULT 0,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_slug_ts ON prices (slug, timestamp)
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def record_prices(self, markets: list[Market]) -> int:
        """Save current prices for all markets. Returns count saved."""
        conn = self._get_conn()
        now = time.time()
        rows = [
            (m.slug, m.yes_price, m.no_price, m.volume_24h, m.liquidity, now)
            for m in markets
            if m.yes_price > 0
        ]
        conn.executemany(
            "INSERT INTO prices (slug, yes_price, no_price, volume_24h, liquidity, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)

    def get_history(
        self, slug: str, hours: float = 24,
    ) -> list[PricePoint]:
        """Get price history for a market."""
        conn = self._get_conn()
        cutoff = time.time() - hours * 3600
        rows = conn.execute(
            "SELECT slug, yes_price, no_price, volume_24h, liquidity, timestamp "
            "FROM prices WHERE slug = ? AND timestamp >= ? ORDER BY timestamp",
            (slug, cutoff),
        ).fetchall()
        return [
            PricePoint(slug=r[0], yes_price=r[1], no_price=r[2],
                       volume_24h=r[3], liquidity=r[4], timestamp=r[5])
            for r in rows
        ]

    def get_price_at(self, slug: str, hours_ago: float) -> float | None:
        """Get the YES price closest to N hours ago."""
        conn = self._get_conn()
        target = time.time() - hours_ago * 3600
        row = conn.execute(
            "SELECT yes_price FROM prices "
            "WHERE slug = ? AND timestamp <= ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (slug, target),
        ).fetchone()
        return row[0] if row else None

    def analyze_trend(self, market: Market) -> TrendAnalysis:
        """Analyze price trends for a market."""
        current = market.yes_price
        p_1h = self.get_price_at(market.slug, 1)
        p_24h = self.get_price_at(market.slug, 24)
        p_7d = self.get_price_at(market.slug, 168)

        trend_1h = (current - p_1h) / p_1h if p_1h and p_1h > 0 else 0.0
        trend_24h = (current - p_24h) / p_24h if p_24h and p_24h > 0 else 0.0
        trend_7d = (current - p_7d) / p_7d if p_7d and p_7d > 0 else 0.0

        history = self.get_history(market.slug, 24)
        prices = [p.yes_price for p in history] if history else [current]

        volatility = 0.0
        if len(prices) >= 2:
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            volatility = variance ** 0.5

        volumes = [p.volume_24h for p in history] if history else []
        vol_trend = 0.0
        if len(volumes) >= 2:
            first_half = sum(volumes[:len(volumes) // 2])
            second_half = sum(volumes[len(volumes) // 2:])
            if first_half > 0:
                vol_trend = (second_half - first_half) / first_half

        support = min(prices) if prices else current
        resistance = max(prices) if prices else current

        if trend_24h > 0.05 and vol_trend > 0:
            signal = "STRONG_BUY"
        elif trend_24h > 0.02:
            signal = "BUY"
        elif trend_24h < -0.05 and vol_trend > 0:
            signal = "STRONG_SELL"
        elif trend_24h < -0.02:
            signal = "SELL"
        else:
            signal = "HOLD"

        return TrendAnalysis(
            slug=market.slug,
            question=market.question,
            current_price=current,
            price_1h_ago=p_1h,
            price_24h_ago=p_24h,
            price_7d_ago=p_7d,
            trend_1h=round(trend_1h, 4),
            trend_24h=round(trend_24h, 4),
            trend_7d=round(trend_7d, 4),
            volatility_24h=round(volatility, 4),
            volume_trend=round(vol_trend, 4),
            support_level=round(support, 4),
            resistance_level=round(resistance, 4),
            signal=signal,
        )

    def cleanup_old(self, days: int = 30) -> int:
        """Delete price records older than N days. Returns count deleted."""
        conn = self._get_conn()
        cutoff = time.time() - days * 86400
        cursor = conn.execute("DELETE FROM prices WHERE timestamp < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount

    def get_tracked_slugs(self) -> list[str]:
        """Return all market slugs with recorded history."""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT slug FROM prices").fetchall()
        return [r[0] for r in rows]
