"""
Primitive 5: Per-Strategy State Manager
Upgraded from flat global state to per-strategy namespaces.
Each strategy hydrates from its own section, preventing double-dipping on crash recovery.
Uses atomic writes to prevent JSON corruption on crash.
"""
import json
import os
import datetime
import sqlite3
from core.logger import get_logger

logger = get_logger(__name__)


class StateManager:
    """
    Primitive 5: Crash-Proof State Manager (Tank Architecture)
    Uses ACID-compliant SQLite with Write-Ahead Logging (WAL) for zero-latency, unbreakable saves.
    """
    def __init__(self, filename="bot_state.db"):
        self.filename = filename
        self.state = {
            "last_trade_date": None,
            "traded_today": False,
            "active_legs": {},
            "strategies": {}
        }
        self._init_db()
        self.load_state()

    def _init_db(self):
        with sqlite3.connect(self.filename) as conn:
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

    def load_state(self):
        try:
            with sqlite3.connect(self.filename) as conn:
                cursor = conn.execute("SELECT value FROM kv_store WHERE key='global_state'")
                row = cursor.fetchone()
                
                if row:
                    data = json.loads(row[0])
                    # Reset if date doesn't match today
                    today_str = str(datetime.datetime.now().date())
                    if data.get("last_trade_date") == today_str:
                        self.state = data
                        if "strategies" not in self.state:
                            self.state["strategies"] = {}
                        logger.info("💾 Recovered Today's Trading State from SQLite Database")
                    else:
                        logger.info("🗑️ Discarding stale state from previous day (SQLite)")
                        self._save_atomic()
                else:
                    logger.info("💿 Initializing clean SQLite state memory.")
                    self._save_atomic()
        except Exception as e:
            logger.error(f"❌ Failed to load SQLite state: {e}. Starting clean.")
            self._save_atomic()

    def save_state(self):
        self._save_atomic()
    
    def _save_atomic(self):
        class TypeSafeEncoder(json.JSONEncoder):
            def default(self, obj):
                import datetime, decimal
                if isinstance(obj, (datetime.datetime, datetime.date)):
                    return obj.isoformat()
                if isinstance(obj, decimal.Decimal):
                    return float(obj)
                return super().default(obj)
                
        try:
            with sqlite3.connect(self.filename) as conn:
                conn.execute(
                    "REPLACE INTO kv_store (key, value) VALUES (?, ?)", 
                    ('global_state', json.dumps(self.state, cls=TypeSafeEncoder))
                )
        except Exception as e:
            logger.critical(f"CRITICAL: SQLite Memory Save Failed: {e}")
            
    def mark_traded_today(self):
        self.state["last_trade_date"] = str(datetime.datetime.now().date())
        self.state["traded_today"] = True
        self.save_state()
        
    def save_active_legs(self, legs_dict):
        """Saves dictionaries describing active leg configurations."""
        self.state["active_legs"] = legs_dict
        self.save_state()

    def clear_active_legs(self):
        self.state["active_legs"] = {}
        self.save_state()

    # ═══════ Per-Strategy State ═══════
    
    def get_strategy_state(self, strategy_key: str) -> dict:
        """Returns the saved state for a specific strategy. Empty dict if none."""
        return self.state.get("strategies", {}).get(strategy_key, {})
    
    def save_strategy_state(self, strategy_key: str, data: dict):
        """Saves state for a specific strategy under its namespace."""
        if "strategies" not in self.state:
            self.state["strategies"] = {}
        self.state["strategies"][strategy_key] = data
        self.save_state()

    def clear_strategy_state(self, strategy_key: str):
        """Clears a specific strategy's state."""
        if "strategies" in self.state and strategy_key in self.state["strategies"]:
            del self.state["strategies"][strategy_key]
            self.save_state()
