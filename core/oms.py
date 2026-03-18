import asyncio
import time
from enum import Enum
from typing import Dict, Optional
from core.events import OrderEvent, FillEvent, SignalEvent
from core.brokers.base_broker import BaseBroker
from core.risk_manager import RiskManager
from core.event_bus import EventBus
from core.logger import get_logger

logger = get_logger(__name__)

class OrderState(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"

class OrderManagementSystem:
    """
    The Global Execution Engine.
    Intercepts OrderEvents, applies pre-trade constraints, manages the
    state machine lifecycle via broker feedback, and yields FillEvents.
    """
    def __init__(self, event_bus: EventBus, broker: BaseBroker, risk_manager: RiskManager):
        self.bus = event_bus
        self.broker = broker
        self.risk_manager = risk_manager
        
        # Internal state tracking
        # order_tag -> {"state": OrderState, "event": OrderEvent, "timestamp": float}
        self.active_orders: Dict[str, dict] = {}
        
        # Memory cleanup interval (purge terminal-state orders older than 60 min)
        self._cleanup_interval = 3600  # seconds
        self._last_cleanup = time.time()

        # Subscribe to OrderEvents
        self.bus.subscribe(OrderEvent, self.on_order_event)

    async def on_order_event(self, event: OrderEvent):
        """Standardizes interception of any strategy trying to place an order."""
        logger.info(f"OMS Received OrderEvent: {event.side} {event.qty}x {event.symbol} [{event.order_tag}]")
        
        # 1. State Machine: Register PENDING
        if event.order_tag in self.active_orders:
            logger.warning(f"OrderTag {event.order_tag} already active in OMS. Ignoring duplicate.")
            return
            
        self.active_orders[event.order_tag] = {
            "state": OrderState.PENDING,
            "event": event,
            "timestamp": time.time()
        }

        # 2. Pre-Trade Circuit Breaker (Delegate to RiskManager)
        is_valid, reason = self.risk_manager.validate_order(event)
        
        if not is_valid:
            logger.critical(f"OMS Circuit Breaker REJECTED Order [{event.order_tag}]: {reason}")
            self._update_state(event.order_tag, OrderState.REJECTED)
            # Notify the strategy so it can clear its pending_orders set
            self._emit_rejection(event, reason)
            return

        # 3. Submit to Broker
        self._update_state(event.order_tag, OrderState.SUBMITTED)
        
        # Execute broker call in another thread to prevent blocking the event loop
        loop = asyncio.get_running_loop()
        try:
            broker_order_id = await loop.run_in_executor(
                None, 
                self.broker.place_order, 
                event.symbol, 
                event.qty, 
                event.side, 
                event.order_type, 
                event.price
            )
            
            if broker_order_id:
                 self._update_state(event.order_tag, OrderState.ACKNOWLEDGED)
                 
                 # Fetch ACTUAL fill price from broker (not the estimate from signal time)
                 actual_fill_price = event.price  # default fallback
                 try:
                     real_ltp = await loop.run_in_executor(
                         None, self.broker.get_quote, event.symbol
                     )
                     if real_ltp and real_ltp > 0:
                         actual_fill_price = real_ltp
                 except Exception:
                     logger.debug(f"Could not fetch actual fill price for {event.symbol}, using estimate")
                 
                 self._update_state(event.order_tag, OrderState.FILLED)
                 
                 # 4. Emit FillEvent with actual fill price
                 fill_event = FillEvent(
                     order_id=str(broker_order_id),
                     order_tag=event.order_tag,
                     symbol=event.symbol,
                     fill_qty=event.qty,
                     fill_price=actual_fill_price,
                     side=event.side,
                     commission=0.0
                 )
                 self.bus.publish(fill_event)
                 logger.info(f"OMS Dispatched FillEvent for {event.order_tag} @ ₹{actual_fill_price:.2f}")
                 
                 # Reduce tracked exposure on BUY fills (closing SELL positions)
                 if event.side == "BUY" and actual_fill_price > 0:
                     self.risk_manager.on_fill_reduce_exposure(
                         event.symbol, event.qty, actual_fill_price, event.side
                     )
                 
            else:
                 self._update_state(event.order_tag, OrderState.REJECTED)
                 logger.error(f"OMS Broker rejected order [{event.order_tag}]")
                 self._emit_rejection(event, "Broker returned None")
                 
        except Exception as e:
            logger.error(f"OMS Error submitting order [{event.order_tag}]: {e}")
            self._update_state(event.order_tag, OrderState.REJECTED)
            self._emit_rejection(event, str(e))
        
        # Periodic cleanup
        self._maybe_cleanup()

    def _emit_rejection(self, event: OrderEvent, reason: str):
        """Emits a zero-qty FillEvent so strategies can clear their pending_orders set."""
        rejection = FillEvent(
            order_id="REJECTED",
            order_tag=event.order_tag,
            symbol=event.symbol,
            fill_qty=0,
            fill_price=0.0,
            side=event.side,
            commission=0.0
        )
        self.bus.publish(rejection)
        logger.warning(f"OMS Rejection notification sent for [{event.order_tag}]: {reason}")

    def _update_state(self, order_tag: str, new_state: OrderState):
        """Internal helper to mutate order state and log."""
        if order_tag in self.active_orders:
            old_state = self.active_orders[order_tag]["state"]
            self.active_orders[order_tag]["state"] = new_state
            logger.debug(f"OMS State Machine: [{order_tag}] {old_state.value} -> {new_state.value}")

    def _maybe_cleanup(self):
        """Purges orders in terminal states older than 60 minutes to prevent memory leak."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
            
        self._last_cleanup = now
        terminal_states = {OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELED}
        stale_tags = [
            tag for tag, data in self.active_orders.items()
            if data["state"] in terminal_states and (now - data["timestamp"]) > self._cleanup_interval
        ]
        for tag in stale_tags:
            del self.active_orders[tag]
        
        if stale_tags:
            logger.info(f"OMS Memory Cleanup: Purged {len(stale_tags)} stale orders. Active: {len(self.active_orders)}")
