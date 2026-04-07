"""
Primitive 3: TimeKeeper — NTP-Synced Exchange Clock
Ensures all strategy time checks are accurate against NSE exchange time,
compensating for local system clock drift on AWS EC2 instances.
"""
import time
import datetime
import threading
from core.logger import get_logger

logger = get_logger(__name__)


class TimeKeeper:
    """
    Singleton-like time source for the entire bot.
    Syncs with NTP on boot, then re-syncs every 4 hours to prevent drift
    on long-running EC2 instances.
    
    Usage:
        from core.timekeeper import timekeeper
        now = timekeeper.now()         # datetime with drift correction
        t = timekeeper.time()          # time-only with drift correction
    """
    def __init__(self):
        self._drift_ms = 0.0
        self._synced = False
        self._resync_interval = 4 * 3600
        self.avg_ping_ms = 10.0
        self.dynamic_drift_threshold = max(1.0, self.avg_ping_ms * 0.5)
        self._start_sync_loop()

    def _start_sync_loop(self):
        """Runs NTP sync on boot and every 4 hours thereafter."""
        def _loop():
            while True:
                self._do_sync()
                time.sleep(self._resync_interval)
        
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def _do_sync(self):
        """Single NTP sync attempt."""
        try:
            import ntplib
            client = ntplib.NTPClient()
            response = client.request('pool.ntp.org', version=3, timeout=5)
            self._drift_ms = response.offset * 1000  # seconds → ms
            self._synced = True
            logger.info(
                f"⏱️ TimeKeeper: NTP synced. Local clock drift: {self._drift_ms:+.1f}ms"
            )
        except ImportError:
            logger.warning("⏱️ TimeKeeper: ntplib not installed. Using local clock (pip install ntplib).")
            self._synced = False
        except Exception as e:
            logger.warning(f"⏱️ TimeKeeper: NTP sync failed ({e}). Using local clock.")
            self._synced = False

    def now(self) -> datetime.datetime:
        """Returns drift-corrected current datetime."""
        raw = datetime.datetime.now()
        if self._synced and abs(self._drift_ms) > self.dynamic_drift_threshold:
            raw += datetime.timedelta(milliseconds=self._drift_ms)
        return raw

    def time(self) -> datetime.time:
        """Returns drift-corrected current time (for strategy window checks)."""
        return self.now().time()

    def today(self) -> datetime.date:
        """Returns drift-corrected current date."""
        return self.now().date()

    def is_weekday(self) -> bool:
        """Returns True if today is Mon-Fri."""
        return self.now().weekday() < 5


# Module-level singleton — import this everywhere
timekeeper = TimeKeeper()
