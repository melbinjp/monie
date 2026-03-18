"""
Primitive 5: Per-Strategy State Manager
Upgraded from flat global state to per-strategy namespaces.
Each strategy hydrates from its own section, preventing double-dipping on crash recovery.
Uses atomic writes to prevent JSON corruption on crash.
"""
import json
import os
import datetime
from core.logger import get_logger

logger = get_logger(__name__)


class StateManager:
    def __init__(self, filename="bot_state.json"):
        self.filename = filename
        self._backup_filename = filename + ".bak"
        self._tmp_filename = filename + ".tmp"
        self.state = {
            "last_trade_date": None,
            "traded_today": False,
            "active_legs": {},
            "strategies": {}   # Per-strategy namespace
        }
        self.load_state()

    def load_state(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    
                    # Reset if date doesn't match today
                    today_str = str(datetime.datetime.now().date())
                    if data.get("last_trade_date") == today_str:
                        self.state = data
                        # Ensure 'strategies' key exists for backward compat
                        if "strategies" not in self.state:
                            self.state["strategies"] = {}
                        logger.info("💾 Recovered Today's Trading State from Disk")
                    else:
                        logger.info("🗑️ Discarding stale state from previous day")
                        self._save_atomic()  # Reset to default
            except json.JSONDecodeError:
                # Primary file is corrupt — try backup
                logger.warning("⚠️ State file corrupted. Attempting backup recovery...")
                if os.path.exists(self._backup_filename):
                    try:
                        with open(self._backup_filename, 'r') as f:
                            data = json.load(f)
                        today_str = str(datetime.datetime.now().date())
                        if data.get("last_trade_date") == today_str:
                            self.state = data
                            logger.info("💾 Recovered from backup state file")
                        else:
                            logger.info("🗑️ Backup is from a different day, starting fresh")
                    except Exception:
                        logger.error("❌ Backup also corrupted. Starting with clean state.")
                else:
                    logger.error("❌ No backup available. Starting with clean state.")
                self._save_atomic()
            except Exception as e:
                logger.error(f"Error loading state: {e}")
                
    def save_state(self):
        """Public save method — delegates to atomic writer."""
        self._save_atomic()
    
    def _save_atomic(self):
        """
        Atomic write: write to .tmp, then os.replace() to target.
        os.replace() is atomic on all OS — if process crashes mid-write,
        the original file is untouched.
        """
        try:
            # 1. Create backup of current file before overwriting
            if os.path.exists(self.filename):
                try:
                    with open(self.filename, 'r') as f:
                        current_data = f.read()
                    if current_data.strip():  # Only backup non-empty files
                        with open(self._backup_filename, 'w') as f:
                            f.write(current_data)
                except Exception:
                    pass  # Backup failure is non-fatal
            
            # 2. Write to temp file
            with open(self._tmp_filename, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
            
            # 3. Atomic swap
            os.replace(self._tmp_filename, self.filename)
            
        except Exception as e:
            logger.error(f"Error saving state atomically: {e}")
            # Fallback: try direct write as last resort
            try:
                with open(self.filename, 'w') as f:
                    json.dump(self.state, f, indent=2, default=str)
            except Exception as e2:
                logger.critical(f"CRITICAL: Cannot save state at all: {e2}")
            
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
