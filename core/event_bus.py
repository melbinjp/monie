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
    Parallel dispatch: async handlers run as bounded tasks, sync handlers
    are offloaded to the thread pool executor.
    """
    def __init__(self, maxsize: int = 10000):
        self.subscribers: Dict[Type[Event], List[Callable]] = {}
        self.queue = asyncio.Queue(maxsize=maxsize)
        self._running = False
        self._task = None

        # Concurrency guard: prevents runaway task explosion during Black Swan events
        self._handler_semaphore = asyncio.Semaphore(50)

        # Observability counters
        self.events_processed = 0
        self.events_dropped = 0
        self._slow_handler_count = 0

    def subscribe(self, event_type: Type[Event], handler: Callable):
        """Registers a callback function for a specific Event type."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {getattr(handler, '__name__', repr(handler))} to {event_type.__name__}")

    def _safe_put(self, event):
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.events_dropped += 1
            logger.error(f"EventBus queue FULL! Dropped {type(event).__name__}")

    def publish(self, event: Event):
        """Pushes an event into the bus (thread-safe, zero-lag)."""
        if hasattr(self, '_loop') and self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._safe_put, event)
        else:
            self._safe_put(event)

    async def _process_events(self):
        """Background loop that pulls events and dispatches them in parallel."""
        self._running = True
        logger.info("EventBus routing engine started (parallel dispatch mode).")
        while self._running:
            try:
                event = await self.queue.get()

                # Find all handlers registered for this event type
                event_type = type(event)
                handlers = self.subscribers.get(event_type, [])

                if handlers:
                    await self._dispatch_parallel(handlers, event, event_type)

                self.events_processed += 1
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus critical failure: {e}", exc_info=True)

    async def _dispatch_parallel(self, handlers: list, event, event_type):
        """
        Dispatches handlers in parallel:
        - Async handlers → asyncio.create_task() bounded by semaphore
        - Sync handlers  → loop.run_in_executor() to avoid blocking the loop
        All errors are caught per-handler to prevent one failure from killing others.
        """
        tasks = []
        loop = asyncio.get_running_loop()

        for handler in handlers:
            handler_name = getattr(handler, '__name__', repr(handler))

            if asyncio.iscoroutinefunction(handler):
                # Wrap async handler with semaphore bound and latency tracking
                task = asyncio.create_task(
                    self._run_async_handler(handler, handler_name, event, event_type)
                )
                tasks.append(task)
            else:
                # Sync handler — run in thread pool, with latency tracking
                task = asyncio.create_task(
                    self._run_sync_handler(loop, handler, handler_name, event, event_type)
                )
                tasks.append(task)

        for i, task in enumerate(tasks):
            h_name = getattr(handlers[i], '__name__', repr(handlers[i]))
            task.set_name(h_name)
            task.add_done_callback(self._task_done_callback)

    def _task_done_callback(self, t: asyncio.Task):
        try:
            if t.exception():
                logger.error(f"Handler {t.get_name()} raised: {t.exception()}")
        except asyncio.CancelledError:
            pass

    async def _run_async_handler(self, handler, handler_name: str, event, event_type):
        """Runs an async handler with semaphore bounding and latency tracking."""
        async with self._handler_semaphore:
            start = time.monotonic()
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Error in async handler {handler_name} processing {event_type.__name__}: {e}",
                    exc_info=True
                )
            finally:
                elapsed_ms = (time.monotonic() - start) * 1000
                if elapsed_ms > 100:
                    self._slow_handler_count += 1
                    logger.warning(
                        f"⚠️ Slow handler [{handler_name}]: {elapsed_ms:.0f}ms "
                        f"processing {event_type.__name__}"
                    )

    async def _run_sync_handler(self, loop, handler, handler_name: str, event, event_type):
        """Runs a sync handler in the thread pool executor with latency tracking."""
        start = time.monotonic()
        try:
            await loop.run_in_executor(None, handler, event)
        except Exception as e:
            logger.error(
                f"Error in sync handler {handler_name} processing {event_type.__name__}: {e}",
                exc_info=True
            )
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > 100:
                self._slow_handler_count += 1
                logger.warning(
                    f"⚠️ Slow handler [{handler_name}]: {elapsed_ms:.0f}ms "
                    f"processing {event_type.__name__}"
                )

    def start(self):
        """Starts the event processing loop."""
        self._loop = asyncio.get_running_loop()
        if not self._task:
            self._task = asyncio.create_task(self._process_events())

    def stop(self):
        """Stops the event processing loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info(f"EventBus stopped. Processed: {self.events_processed}, Dropped: {self.events_dropped}, Slow: {self._slow_handler_count}")

    def get_stats(self) -> dict:
        """Returns bus health metrics for monitoring (e.g., Telegram /bus command)."""
        return {
            "queue_depth": self.queue.qsize(),
            "queue_max": self.queue.maxsize,
            "events_processed": self.events_processed,
            "events_dropped": self.events_dropped,
            "subscriber_count": sum(len(h) for h in self.subscribers.values()),
            "slow_handlers": self._slow_handler_count,
        }

