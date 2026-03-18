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
    Syncs with NTP on boot, then applies drift offset to all time queries.
    
    Usage:
        from core.timekeeper import timekeeper
        now = timekeeper.now()         # datetime with drift correction
        t = timekeeper.time()          # time-only with drift correction
    """
    def __init__(self):
        self._drift_ms = 0.0  # milliseconds ahead/behind NTP
        self._synced = False
        self._sync()

    def _sync(self):
        """Attempt NTP sync in background to avoid blocking startup."""
        def _do_sync():
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

        t = threading.Thread(target=_do_sync, daemon=True)
        t.start()

    def now(self) -> datetime.datetime:
        """Returns drift-corrected current datetime."""
        raw = datetime.datetime.now()
        if self._synced and abs(self._drift_ms) > 100:  # Only correct if drift > 100ms
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
