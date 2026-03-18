import asyncio
import time
from typing import Callable, Dict, List, Type
from core.events import Event
from core.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    """
    Central Asynchronous Message Broker.
    Routes Event dataclasses from publishers to registered subscribers.
    Bounded queue prevents OOM during market crashes.
    """
    def __init__(self, maxsize: int = 10000):
        self.subscribers: Dict[Type[Event], List[Callable]] = {}
        self.queue = asyncio.Queue(maxsize=maxsize)
        self._running = False
        self._task = None
        
        # Observability counters
        self.events_processed = 0
        self.events_dropped = 0

    def subscribe(self, event_type: Type[Event], handler: Callable):
        """Registers a callback function for a specific Event type."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {getattr(handler, '__name__', repr(handler))} to {event_type.__name__}")

    def publish(self, event: Event):
        """Pushes an event into the bus (non-blocking)."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.events_dropped += 1
            logger.error(f"EventBus queue FULL ({self.queue.maxsize})! Dropped {type(event).__name__}. Total dropped: {self.events_dropped}")

    async def _process_events(self):
        """Background loop that pulls events and dispatches them."""
        self._running = True
        logger.info("EventBus routing engine started.")
        while self._running:
            try:
                event = await self.queue.get()
                
                # Find all handlers registered for this event type
                event_type = type(event)
                handlers = self.subscribers.get(event_type, [])
                
                for handler in handlers:
                    try:
                        # Handlers can be sync or async
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)
                    except Exception as e:
                        handler_name = getattr(handler, '__name__', repr(handler))
                        logger.error(f"Error in {handler_name} processing {event_type.__name__}: {e}", exc_info=True)
                        
                self.events_processed += 1
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus critical failure: {e}", exc_info=True)

    def start(self):
        """Starts the event processing loop."""
        if not self._task:
            self._task = asyncio.create_task(self._process_events())

    def stop(self):
        """Stops the event processing loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info(f"EventBus stopped. Processed: {self.events_processed}, Dropped: {self.events_dropped}")

    def get_stats(self) -> dict:
        """Returns bus health metrics for monitoring (e.g., Telegram /bus command)."""
        return {
            "queue_depth": self.queue.qsize(),
            "queue_max": self.queue.maxsize,
            "events_processed": self.events_processed,
            "events_dropped": self.events_dropped,
            "subscriber_count": sum(len(h) for h in self.subscribers.values()),
        }
