"""
Strategy Orchestrator — Central Multi-Strategy Manager
Wires strategies to EventBus. Manages lifecycle (EOD square-off all).
Includes graceful degradation: auto-disables strategies after consecutive errors.
"""
from core.logger import get_logger
from core.events import CleanTickEvent, FillEvent
from core.event_bus import EventBus

logger = get_logger(__name__)

# Max consecutive errors before auto-disabling a strategy for the day
MAX_CONSECUTIVE_ERRORS = 5


class StrategyOrchestrator:
    """
    Manages multiple strategies. Wires them to the Event Bus to receive asynchronous
    updates and manages global lifecycle constraints.
    """
    def __init__(self, strategies: list, event_bus: EventBus, telegram=None):
        self.strategies = strategies
        self.event_bus = event_bus
        self.telegram = telegram
        
        # Per-strategy error tracking for graceful degradation
        self._error_counts = {s.get_name(): 0 for s in strategies}
        self._disabled_strategies = set()
        
        names = [s.get_name() for s in self.strategies]
        
        # Wire up strategies to Event Bus
        for strategy in self.strategies:
            # Tick handler with should_run() gating and error recovery
            def make_tick_handler(strat):
                def tick_handler(event: CleanTickEvent):
                    name = strat.get_name()
                    if name in self._disabled_strategies:
                        return
                    if not strat.should_run():
                        return
                    try:
                        strat.on_tick(event)
                        # Reset error count on success
                        self._error_counts[name] = 0
                    except Exception as e:
                        self._handle_strategy_error(strat, "on_tick", e)
                # Set explicit name for EventBus debug logging
                tick_handler.__name__ = f"{strat.get_name()}_on_tick"
                return tick_handler
                
            self.event_bus.subscribe(CleanTickEvent, make_tick_handler(strategy))
            
            # Fill handler with error recovery
            if hasattr(strategy, 'on_fill'):
                def make_fill_handler(strat):
                    def fill_handler(event: FillEvent):
                        name = strat.get_name()
                        if name in self._disabled_strategies:
                            return
                        try:
                            strat.on_fill(event)
                            self._error_counts[name] = 0
                        except Exception as e:
                            self._handle_strategy_error(strat, "on_fill", e)
                            # Critical: clear pending_orders on fill error to prevent deadlock
                            if hasattr(strat, 'pending_orders'):
                                strat.pending_orders.discard(event.order_tag)
                                logger.warning(f"Force-cleared order_tag {event.order_tag} from {name} pending set")
                    fill_handler.__name__ = f"{strat.get_name()}_on_fill"
                    return fill_handler
                    
                self.event_bus.subscribe(FillEvent, make_fill_handler(strategy))
                
        logger.info(f"🎯 Orchestrator initialized & wired {len(strategies)} strategies: {names}")
        if telegram:
            telegram.send_message(
                f"🎯 **Reactive Strategy Orchestrator Active**\n"
                f"Event Bus Routing for {len(strategies)} strategies:\n" +
                "\n".join(f"  • {n}" for n in names)
            )

    def _handle_strategy_error(self, strategy, method: str, error: Exception):
        """Tracks consecutive errors and auto-disables strategies that are failing repeatedly."""
        name = strategy.get_name()
        self._error_counts[name] = self._error_counts.get(name, 0) + 1
        count = self._error_counts[name]
        
        logger.error(f"❌ {name}.{method}() error ({count}/{MAX_CONSECUTIVE_ERRORS}): {error}", exc_info=True)
        
        if count >= MAX_CONSECUTIVE_ERRORS:
            self._disabled_strategies.add(name)
            disable_msg = (
                f"🚨 **STRATEGY AUTO-DISABLED: {name}**\n"
                f"{count} consecutive errors. Last: {error}\n"
                f"Strategy will not receive events for the rest of the day."
            )
            logger.critical(disable_msg)
            if self.telegram:
                self.telegram.send_message(disable_msg)

    def square_off_all(self, reason_msg=None):
        """Emergency liquidation across ALL strategies (including disabled ones)."""
        msg = reason_msg or "🛑 Orchestrator: Force-closing all strategy positions"
        logger.warning(msg)
        if self.telegram:
            self.telegram.send_message(msg)
        
        for strategy in self.strategies:
            try:
                strategy.square_off_all(reason_msg=msg)
            except Exception as e:
                logger.error(f"❌ Failed to square off {strategy.get_name()}: {e}")

    def activate_hedge_mode(self):
        """Signals all strategies to transition into a protective stance."""
        msg = "🛡️ Orchestrator: HEDGE MODE ACTIVATED across all active strategies. Tightening Stops."
        logger.warning(msg)
        if self.telegram:
            self.telegram.send_message(msg)
            
        for strategy in self.strategies:
            if hasattr(strategy, 'activate_hedge_mode'):
                try:
                    strategy.activate_hedge_mode()
                except Exception as e:
                    logger.error(f"❌ Failed to activate hedge mode on {strategy.get_name()}: {e}")

    @property
    def traded_today(self):
        """Returns True if ANY strategy has traded today."""
        return any(getattr(s, 'traded_today', False) for s in self.strategies)
