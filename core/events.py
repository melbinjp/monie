from dataclasses import dataclass
from typing import Optional, Any
import time

@dataclass(frozen=True)
class Event:
    """Base Event class for the Event Bus."""
    timestamp: float = 0.0
    
    def __post_init__(self):
        # Allow setting default timestamp at creation time if not provided
        if not self.timestamp:
            object.__setattr__(self, 'timestamp', time.time())

@dataclass(frozen=True)
class TickEvent(Event):
    """Normalized Market Data Tick."""
    symbol: str = ""
    ltp: float = 0.0
    vix: Optional[float] = None
    
@dataclass(frozen=True)
class CleanTickEvent(Event):
    """Sanitized Market Data Tick (Filtered by DataSanitizer)."""
    symbol: str = ""
    ltp: float = 0.0
    vix: Optional[float] = None
    
@dataclass(frozen=True)
class SignalEvent(Event):
    """A Strategy's intent to trade."""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    order_type: str = "MARKET"
    price: float = 0.0
    reason: str = ""
    
@dataclass(frozen=True)
class OrderEvent(Event):
    """A validated Order bound for the Broker."""
    order_tag: str = ""      # e.g., 'MONIE-Straddle-123456-abc'
    strategy_id: str = ""
    symbol: str = ""
    qty: int = 0
    side: str = ""           # "BUY" or "SELL"
    order_type: str = "MARKET"
    price: float = 0.0

@dataclass(frozen=True)
class FillEvent(Event):
    """Broker confirmation of execution."""
    order_id: str = ""       # Broker's ID
    order_tag: str = ""      # Our Idempotent Tag
    symbol: str = ""
    fill_qty: int = 0
    fill_price: float = 0.0
    side: str = ""
    commission: float = 0.0
    ideal_time: float = 0.0          # Exact ping of intent
    actual_time: float = 0.0         # Exact ping of broker fill
    decision_latency_ms: float = 0.0 # Time blocked in engine internal queues
    network_latency_ms: float = 0.0  # Time waiting for broker APIs

@dataclass(frozen=True)
class SystemEvent(Event):
    """System-level commands (e.g., EOD Square-off, Emergency Halt)."""
    command: str = ""
    payload: Any = None
