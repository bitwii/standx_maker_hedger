"""
State Machine for StandX Maker Hedger
Manages bot states to prevent race conditions and duplicate orders
"""
import logging
from enum import Enum, auto
from typing import Optional, Dict, Set
from decimal import Decimal
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)


class BotState(Enum):
    """Main bot states"""
    IDLE = auto()           # No orders, no positions
    PLACING = auto()        # Placing market making orders, waiting for confirmation
    MARKET_MAKING = auto()  # Active market making, orders confirmed
    CANCELLING = auto()     # Cancelling orders
    HEDGING = auto()        # Executing hedge
    CLOSING = auto()        # Has position, closing


class OrderState(Enum):
    """Individual order states"""
    PENDING = auto()        # Sent, waiting for WS confirmation
    OPEN = auto()           # Confirmed open
    PARTIAL_FILLED = auto() # Partially filled
    FILLED = auto()         # Fully filled
    CANCELLING = auto()     # Cancel requested
    CANCELLED = auto()      # Cancelled


@dataclass
class TrackedOrder:
    """Track individual order state"""
    cl_ord_id: str
    order_id: Optional[str] = None
    side: str = ""
    price: Decimal = Decimal('0')
    quantity: Decimal = Decimal('0')
    filled_qty: Decimal = Decimal('0')
    state: OrderState = OrderState.PENDING
    is_close_order: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def remaining_qty(self) -> Decimal:
        return self.quantity - self.filled_qty

    @property
    def is_fully_filled(self) -> bool:
        return self.filled_qty >= self.quantity


class StateMachine:
    """
    State machine for managing bot lifecycle.
    Prevents race conditions and duplicate orders.
    """

    # Timeout for PLACING state (seconds)
    PLACING_TIMEOUT = 10
    # Timeout for CANCELLING state (seconds)
    CANCELLING_TIMEOUT = 10

    def __init__(self):
        self._state = BotState.IDLE
        self._previous_state = BotState.IDLE

        # Order tracking by cl_ord_id
        self._orders: Dict[str, TrackedOrder] = {}
        # Map order_id -> cl_ord_id for WS callbacks
        self._order_id_map: Dict[str, str] = {}

        # Pending orders waiting for confirmation
        self._pending_mm_orders: Set[str] = set()  # Market making orders
        self._pending_cancel_orders: Set[str] = set()  # Orders being cancelled

        # State transition timestamp
        self._state_changed_at = time.time()

        logger.info(f"StateMachine initialized, state={self._state.name}")

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def state_name(self) -> str:
        return self._state.name

    def _set_state(self, new_state: BotState):
        """Internal state transition"""
        if new_state != self._state:
            self._previous_state = self._state
            self._state = new_state
            self._state_changed_at = time.time()
            logger.info(f"State: {self._previous_state.name} -> {new_state.name}")

    def _state_age(self) -> float:
        """Seconds since last state change"""
        return time.time() - self._state_changed_at

    # ========== State Query Methods ==========

    def can_place_orders(self) -> bool:
        """Check if we can place new market making orders"""
        if self._state == BotState.PLACING:
            # Check timeout
            if self._state_age() > self.PLACING_TIMEOUT:
                logger.warning("PLACING state timeout, allowing new orders")
                return True
            return False
        return self._state in (BotState.IDLE, BotState.MARKET_MAKING)

    def can_cancel_orders(self) -> bool:
        """Check if we can cancel orders"""
        # Never cancel during hedging
        if self._state == BotState.HEDGING:
            return False
        return self._state in (BotState.MARKET_MAKING, BotState.CLOSING)

    def can_check_orders(self) -> bool:
        """Check if we should run order check logic"""
        return self._state == BotState.MARKET_MAKING

    def is_hedging(self) -> bool:
        return self._state == BotState.HEDGING

    def is_closing(self) -> bool:
        return self._state == BotState.CLOSING

    # ========== Order Tracking Methods ==========

    def track_order(self, cl_ord_id: str, side: str, price: Decimal,
                    quantity: Decimal, is_close_order: bool = False) -> TrackedOrder:
        """Start tracking a new order"""
        order = TrackedOrder(
            cl_ord_id=cl_ord_id,
            side=side,
            price=price,
            quantity=quantity,
            is_close_order=is_close_order
        )
        self._orders[cl_ord_id] = order
        logger.debug(f"Tracking order: {cl_ord_id} {side} {quantity}@{price}")
        return order

    def get_order(self, cl_ord_id: str) -> Optional[TrackedOrder]:
        return self._orders.get(cl_ord_id)

    def get_order_by_id(self, order_id: str) -> Optional[TrackedOrder]:
        cl_ord_id = self._order_id_map.get(order_id)
        if cl_ord_id:
            return self._orders.get(cl_ord_id)
        return None

    def get_market_making_orders(self) -> Dict[str, TrackedOrder]:
        """Get all non-close orders"""
        return {k: v for k, v in self._orders.items() if not v.is_close_order}

    def get_close_order(self) -> Optional[TrackedOrder]:
        """Get the current close order if any"""
        for order in self._orders.values():
            if order.is_close_order and order.state in (OrderState.PENDING, OrderState.OPEN):
                return order
        return None

    def remove_order(self, cl_ord_id: str):
        """Remove order from tracking"""
        if cl_ord_id in self._orders:
            order = self._orders.pop(cl_ord_id)
            if order.order_id and order.order_id in self._order_id_map:
                del self._order_id_map[order.order_id]
            logger.debug(f"Removed order: {cl_ord_id}")

    # ========== State Transition Methods ==========

    def on_placing_orders(self, cl_ord_ids: list):
        """Called when starting to place market making orders"""
        self._pending_mm_orders = set(cl_ord_ids)
        self._set_state(BotState.PLACING)

    def on_order_confirmed(self, cl_ord_id: str, order_id: str):
        """Called when WS confirms order is open"""
        order = self._orders.get(cl_ord_id)
        if order:
            order.order_id = order_id
            order.state = OrderState.OPEN
            self._order_id_map[order_id] = cl_ord_id

        # Remove from pending
        self._pending_mm_orders.discard(cl_ord_id)

        # Check if all MM orders confirmed
        if not self._pending_mm_orders and self._state == BotState.PLACING:
            self._set_state(BotState.MARKET_MAKING)

    def on_order_filled(self, order_id: str, filled_qty: Decimal) -> Optional[TrackedOrder]:
        """Called when order is filled (full or partial)"""
        order = self.get_order_by_id(order_id)
        if not order:
            logger.warning(f"Filled order {order_id} not tracked")
            return None

        order.filled_qty = filled_qty
        if order.is_fully_filled:
            order.state = OrderState.FILLED
        else:
            order.state = OrderState.PARTIAL_FILLED

        return order

    def on_cancelling_orders(self, cl_ord_ids: list):
        """Called when starting to cancel orders"""
        self._pending_cancel_orders = set(cl_ord_ids)
        for cl_ord_id in cl_ord_ids:
            order = self._orders.get(cl_ord_id)
            if order:
                order.state = OrderState.CANCELLING
        self._set_state(BotState.CANCELLING)

    def on_order_cancelled(self, order_id: str):
        """Called when WS confirms order is cancelled"""
        order = self.get_order_by_id(order_id)
        if order:
            order.state = OrderState.CANCELLED
            self._pending_cancel_orders.discard(order.cl_ord_id)
            self.remove_order(order.cl_ord_id)

        # Check if all cancels confirmed
        if not self._pending_cancel_orders and self._state == BotState.CANCELLING:
            self._set_state(BotState.IDLE)

    def on_hedging_start(self):
        """Called when starting hedge operation"""
        self._set_state(BotState.HEDGING)

    def on_hedging_complete(self):
        """Called when hedge is complete, transition to closing"""
        self._set_state(BotState.CLOSING)

    def on_close_order_filled(self):
        """Called when close order is fully filled"""
        # Remove close order from tracking
        close_order = self.get_close_order()
        if close_order:
            self.remove_order(close_order.cl_ord_id)

        # Check if we have any MM orders left
        mm_orders = self.get_market_making_orders()
        if mm_orders:
            self._set_state(BotState.MARKET_MAKING)
        else:
            self._set_state(BotState.IDLE)

    def on_position_closed(self):
        """Called when all positions are closed"""
        # Clear close order tracking
        close_order = self.get_close_order()
        if close_order:
            self.remove_order(close_order.cl_ord_id)

        # Transition based on remaining orders
        mm_orders = self.get_market_making_orders()
        active_mm = [o for o in mm_orders.values() if o.state == OrderState.OPEN]
        if active_mm:
            self._set_state(BotState.MARKET_MAKING)
        else:
            self._set_state(BotState.IDLE)

    # ========== Utility Methods ==========

    def get_orders_to_cancel(self) -> list:
        """Get cl_ord_ids of orders that can be cancelled (excludes close orders)"""
        result = []
        for cl_ord_id, order in self._orders.items():
            if not order.is_close_order and order.state == OrderState.OPEN:
                result.append(cl_ord_id)
        return result

    def clear_all(self):
        """Clear all tracking (for reset)"""
        self._orders.clear()
        self._order_id_map.clear()
        self._pending_mm_orders.clear()
        self._pending_cancel_orders.clear()
        self._set_state(BotState.IDLE)

    def get_status(self) -> dict:
        """Get current state machine status"""
        return {
            'state': self._state.name,
            'state_age': self._state_age(),
            'tracked_orders': len(self._orders),
            'pending_mm': len(self._pending_mm_orders),
            'pending_cancel': len(self._pending_cancel_orders),
        }
