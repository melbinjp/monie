"""
Base Broker Interface
Standardizes methods for Shoonya, Upstox, etc.
Primitive 4: Idempotent Orders — every order carries a unique tag to prevent duplicates.
"""
import time
import hashlib
from abc import ABC, abstractmethod
from core.logger import get_logger

logger = get_logger(__name__)


class BaseBroker(ABC):
    
    def generate_order_tag(self, strategy: str, symbol: str, side: str, reason: str = "") -> str:
        """
        Generates a unique, idempotent order tag.
        If the same order is accidentally retried, the exchange can deduplicate it.
        Format: MONIE-{strategy}-{timestamp_ms}-{hash4}
        """
        ts = int(time.time() * 1000)
        raw = f"{strategy}-{symbol}-{side}-{reason}-{ts}"
        h = hashlib.md5(raw.encode()).hexdigest()[:4]
        tag = f"MONIE-{strategy[:6]}-{ts}-{h}"
        return tag[:25]  # Upstox max tag length is 20-25 chars
    
    @abstractmethod
    def authenticate(self):
        """Logs in to the broker API."""
        pass
        
    @abstractmethod
    def get_quote(self, symbol: str):
        """Fetches live LTP (Last Traded Price)."""
        pass
        
    @abstractmethod
    def place_order(self, symbol: str, quantity: int, side: str, order_type: str = "MARKET", price: float = 0.0, order_tag: str = None):
        """Places a BUY/SELL order."""
        pass
        
    @abstractmethod
    def get_positions(self):
        """Returns current open positions."""
        pass
        
    @abstractmethod
    def get_pnl(self):
        """Returns total PnL for the day."""
        pass

    @abstractmethod
    def get_cached_quote(self, symbol: str) -> float:
        """Returns non-blocking cached Last Traded Price natively without REST delays."""
        pass
