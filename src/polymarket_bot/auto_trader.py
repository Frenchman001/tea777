"""Auto-execution module — places orders via Polymarket CLOB API.

Requires POLYMARKET_PRIVATE_KEY and POLYMARKET_API_KEY environment variables.
Uses py-clob-client for order placement on Polygon.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from polymarket_bot.config import Config
from polymarket_bot.liquidity import LiquidityCheck
from polymarket_bot.smart_alerts import Alert

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class TradeOrder:
    market_slug: str
    token_id: str
    side: OrderSide
    price: float
    size: float
    status: OrderStatus = OrderStatus.PENDING
    order_id: str = ""
    filled_size: float = 0.0
    error: str = ""
    created_at: float = 0.0

    @property
    def cost_usd(self) -> float:
        return self.price * self.size


@dataclass
class TradeResult:
    order: TradeOrder
    success: bool
    message: str
    tx_hash: str = ""


@dataclass
class TradingSession:
    orders: list[TradeOrder] = field(default_factory=list)
    total_invested: float = 0.0
    total_fees: float = 0.0
    start_time: float = 0.0
    max_bankroll_pct: float = 0.25

    @property
    def num_trades(self) -> int:
        return len([o for o in self.orders if o.status == OrderStatus.FILLED])


class AutoTrader:
    """Automated trade execution engine.

    Places limit orders via the Polymarket CLOB API when conditions are met.
    Requires py-clob-client and valid credentials.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._session = TradingSession(start_time=time.time())
        self._clob_client = None
        self._dry_run = not config.auto_trade

    def initialize(self) -> bool:
        """Initialize the CLOB client with credentials.

        Returns True if ready to trade, False if in dry-run mode.
        """
        if not self.config.private_key:
            logger.warning("No private key configured — running in dry-run mode")
            self._dry_run = True
            return False

        try:
            from py_clob_client.client import ClobClient

            self._clob_client = ClobClient(
                host=self.config.clob_host,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
                funder=self.config.funder_address,
            )
            logger.info("CLOB client initialized, ready to trade")
            return True
        except ImportError:
            logger.warning(
                "py-clob-client not installed. "
                "Install with: pip install 'polymarket-bot[trading]'"
            )
            self._dry_run = True
            return False
        except Exception as e:
            logger.error("Failed to initialize CLOB client: %s", e)
            self._dry_run = True
            return False

    def execute_alert(
        self,
        alert: Alert,
        liquidity: LiquidityCheck | None = None,
        token_id: str = "",
    ) -> TradeResult:
        """Execute a trade based on an alert, with safety checks."""
        if self._session.total_invested + alert.recommended_bet_usd > (
            self.config.max_bet_size_usd * 10
        ):
            return TradeResult(
                order=TradeOrder(
                    market_slug=alert.market_slug,
                    token_id=token_id,
                    side=OrderSide.BUY,
                    price=0,
                    size=0,
                ),
                success=False,
                message="Portfolio allocation limit reached",
            )

        if liquidity and not liquidity.is_safe:
            return TradeResult(
                order=TradeOrder(
                    market_slug=alert.market_slug,
                    token_id=token_id,
                    side=OrderSide.BUY,
                    price=0,
                    size=0,
                ),
                success=False,
                message=(
                    f"Insufficient liquidity: {liquidity.available_depth_usd:.0f} USD, "
                    f"slippage {liquidity.slippage_pct:.1f}%"
                ),
            )

        price = liquidity.avg_fill_price if liquidity else 0.5
        size = alert.recommended_bet_usd / price if price > 0 else 0

        order = TradeOrder(
            market_slug=alert.market_slug,
            token_id=token_id,
            side=OrderSide.BUY,
            price=round(price, 4),
            size=round(size, 2),
            created_at=time.time(),
        )

        if self._dry_run:
            order.status = OrderStatus.PENDING
            self._session.orders.append(order)
            return TradeResult(
                order=order,
                success=True,
                message=f"[DRY RUN] Would buy {size:.1f} shares @ {price:.4f} "
                        f"(${alert.recommended_bet_usd:.2f})",
            )

        return self._place_order(order)

    def _place_order(self, order: TradeOrder) -> TradeResult:
        """Place a limit order via the CLOB API."""
        if self._clob_client is None:
            return TradeResult(
                order=order, success=False,
                message="CLOB client not initialized",
            )

        try:
            from py_clob_client.order_builder.constants import BUY

            resp = self._clob_client.create_and_post_order(
                order_args={
                    "token_id": order.token_id,
                    "price": order.price,
                    "size": order.size,
                    "side": BUY,
                },
            )

            if resp and resp.get("success"):
                order.status = OrderStatus.PLACED
                order.order_id = resp.get("orderID", "")
                self._session.orders.append(order)
                self._session.total_invested += order.cost_usd
                return TradeResult(
                    order=order, success=True,
                    message=f"Order placed: {order.order_id}",
                )
            else:
                order.status = OrderStatus.FAILED
                order.error = str(resp)
                return TradeResult(
                    order=order, success=False,
                    message=f"Order rejected: {resp}",
                )
        except Exception as e:
            order.status = OrderStatus.FAILED
            order.error = str(e)
            return TradeResult(
                order=order, success=False,
                message=f"Order failed: {e}",
            )

    def get_session_summary(self) -> dict:
        """Return a summary of the trading session."""
        filled = [o for o in self._session.orders if o.status in (
            OrderStatus.FILLED, OrderStatus.PLACED,
        )]
        pending = [o for o in self._session.orders if o.status == OrderStatus.PENDING]
        failed = [o for o in self._session.orders if o.status == OrderStatus.FAILED]

        return {
            "mode": "DRY RUN" if self._dry_run else "LIVE",
            "total_orders": len(self._session.orders),
            "filled": len(filled),
            "pending": len(pending),
            "failed": len(failed),
            "total_invested_usd": round(self._session.total_invested, 2),
            "duration_sec": round(time.time() - self._session.start_time, 1),
        }
