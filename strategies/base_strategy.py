"""
Base Strategy Interface — Enhanced for Multi-Strategy Orchestration
Parent class for all trading strategies.
"""
from abc import ABC, abstractmethod
from core.brokers.base_broker import BaseBroker
from core.risk_manager import RiskManager
from core.logger import get_logger
from core.event_bus import EventBus
from core.events import CleanTickEvent, FillEvent


class BaseStrategy(ABC):
    def __init__(self, broker: BaseBroker, risk_manager: RiskManager, event_bus: EventBus):
        self.broker = broker
        self.risk_manager = risk_manager
        self.event_bus = event_bus
        self.active_positions = {}
        self.logger = get_logger(__name__, strategy_name=self.get_name())

    @abstractmethod
    def get_name(self) -> str:
        """Returns a human-readable strategy name for logging and state keys."""
        pass

    def get_state_key(self) -> str:
        """Returns a unique key for per-strategy state persistence."""
        return self.get_name().replace(" ", "_").lower()

    @abstractmethod
    def should_run(self) -> bool:
        """
        Called by the Orchestrator every cycle.
        Returns True if this strategy is eligible to run right now
        based on market conditions (VIX, time, day of week, etc).
        """
        pass

    @abstractmethod
    def on_tick(self, event: CleanTickEvent):
        """Handle incoming sanitized market data."""
        pass

    @abstractmethod
    def on_fill(self, event: FillEvent):
        """Handle execution confirmation from the OMS."""
        pass

    @abstractmethod
    def square_off_all(self, reason_msg=None):
        """Emergency or EOD liquidation of all positions."""
        pass

    def check_risk(self):
        """Wrapper to check if trading is allowed."""
        allowed, reason = self.risk_manager.can_trade()
        if not allowed:
            self.logger.warning(f"🚫 Strategy Halted: {reason}")
        return allowed
