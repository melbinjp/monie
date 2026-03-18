import os
import json
import datetime
from core.logger import get_logger

logger = get_logger(__name__)


class StagingManager:
    """
    Mathematical Firmware Lock — Levels 1 through 5.
    Reads daily bot metrics and scores execution correctness.
    Physically prevents UPSTOX Live APIs until Level 5 is achieved.
    Permanent audit trail in logs/staging_journal.log.
    Uses atomic writes to prevent JSON corruption on crash.
    """
    def __init__(self, staging_file="staging_state.json"):
        self.staging_file = staging_file
        self._tmp_file = staging_file + ".tmp"
        self._bak_file = staging_file + ".bak"
        self.log_dir = "logs"
        os.makedirs(self.log_dir, exist_ok=True)
        
        import logging as _logging
        _base = _logging.getLogger("StagingManager")
        _base.setLevel(_logging.INFO)
        fh = _logging.FileHandler(os.path.join(self.log_dir, "staging_journal.log"))
        fh.setFormatter(_logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        if not _base.handlers:
            _base.addHandler(fh)
        
        self.state = self.load_staging_state()
        self.staging_logger = _logging.LoggerAdapter(_base, {})

    def load_staging_state(self):
        if os.path.exists(self.staging_file):
            try:
                with open(self.staging_file, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning("⚠️ Staging JSON corrupted. Trying backup...")
                if os.path.exists(self._bak_file):
                    try:
                        with open(self._bak_file, "r") as f:
                            return json.load(f)
                    except Exception:
                        pass
                logger.error("❌ Staging state unrecoverable. Resetting.")
            except Exception as e:
                logger.error(f"⚠️ Staging load error: {e}")
                
        default_state = {
            "current_level": 1,
            "level_1_clean_days": 0,
            "level_2_accurate_entries": 0,
            "level_3_clean_sl_exits": 0,
            "level_4_start_date": str(datetime.datetime.now().date()),
            "level_4_wins": 0,
            "level_4_total": 0,
            "level_4_net_pnl": 0.0,
            "last_processed_date": None,
            "today_metrics": {}
        }
        self._save_atomic(default_state)
        return default_state

    def save_staging_state(self, state=None):
        """Public save — delegates to atomic writer."""
        self._save_atomic(state or self.state)

    def _save_atomic(self, state):
        """Atomic write: tmp → os.replace(). Same pattern as StateManager."""
        try:
            # Backup current file
            if os.path.exists(self.staging_file):
                try:
                    with open(self.staging_file, 'r') as f:
                        current = f.read()
                    if current.strip():
                        with open(self._bak_file, 'w') as f:
                            f.write(current)
                except Exception:
                    pass
            
            # Write to tmp, then atomic swap
            with open(self._tmp_file, "w") as f:
                json.dump(state, f, indent=4)
            os.replace(self._tmp_file, self.staging_file)
        except Exception as e:
            logger.error(f"Staging atomic write failed: {e}")
            # Fallback direct write
            try:
                with open(self.staging_file, "w") as f:
                    json.dump(state, f, indent=4)
            except Exception as e2:
                logger.critical(f"CRITICAL: Cannot save staging state: {e2}")
            
    def is_live_trading_allowed(self):
        return self.state.get("current_level", 1) >= 5
        
    def get_current_level(self):
        return self.state.get("current_level", 1)

    def log_critical_error(self, error_msg):
        """Called by main.py on crashes. Resets Level 1 progress."""
        self.staging_logger.error(f"FATAL EXCEPTION: {error_msg}")
        if self.state.get("current_level", 1) == 1:
            self.staging_logger.warning("Level 1 failed — resetting clean days to 0.")
            self.state["level_1_clean_days"] = 0
            self.save_staging_state()

    # ----- Intraday Metric Collectors -----

    def record_entry_accuracy(self, entry_time_str, premium_diff):
        """Called by strategy after executing straddle."""
        metrics = self.state.get("today_metrics", {})
        metrics["entry_time"] = entry_time_str
        metrics["premium_diff"] = premium_diff
        self.state["today_metrics"] = metrics
        self.save_staging_state()
        self.staging_logger.info(f"Entry recorded: time={entry_time_str}, premium_diff=₹{premium_diff:.2f}")

    def record_sl_exit(self, trigger_price, fill_price):
        """Called by strategy when SL fires."""
        slippage = abs(fill_price - trigger_price)
        metrics = self.state.get("today_metrics", {})
        sl_exits = metrics.get("sl_exits", [])
        sl_exits.append({"trigger": trigger_price, "fill": fill_price, "slippage": slippage})
        metrics["sl_exits"] = sl_exits
        self.state["today_metrics"] = metrics
        self.save_staging_state()
        self.staging_logger.info(f"SL exit recorded: trigger=₹{trigger_price:.1f}, fill=₹{fill_price:.1f}, slippage=₹{slippage:.2f}")

    def record_daily_pnl(self, pnl):
        """Called at EOD."""
        metrics = self.state.get("today_metrics", {})
        metrics["daily_pnl"] = pnl
        self.state["today_metrics"] = metrics
        self.save_staging_state()

    # ----- End-of-Day Evaluation -----

    def evaluate_daily_performance(self, bot_state_dict):
        """Grades the bot at 15:30 and handles Level advancement."""
        today_str = str(datetime.datetime.now().date())
        if self.state.get("last_processed_date") == today_str:
            return False
            
        self.staging_logger.info("--- End-of-Day Evaluation ---")
        level_up = False
        lvl = self.state.get("current_level", 1)
        metrics = self.state.get("today_metrics", {})
        
        if lvl == 1:
            self.state["level_1_clean_days"] += 1
            progress = self.state["level_1_clean_days"]
            self.staging_logger.info(f"Level 1 Stability: {progress}/5 clean days")
            if progress >= 5:
                self.state["current_level"] = 2
                self.staging_logger.info("⭐ LEVEL UP → Level 2 (Execution Accuracy)")
                level_up = True
                
        elif lvl == 2:
            entry_time = metrics.get("entry_time", "")
            premium_diff = metrics.get("premium_diff", 999)
            
            entry_ok = False
            if entry_time:
                try:
                    t = datetime.datetime.strptime(entry_time, "%H:%M:%S").time()
                    entry_ok = datetime.time(9, 21) <= t <= datetime.time(9, 25)
                except ValueError:
                    pass
            
            if entry_ok and premium_diff < 5.0:
                self.state["level_2_accurate_entries"] += 1
                self.staging_logger.info(f"Level 2 Execution: {self.state['level_2_accurate_entries']}/10 accurate entries")
            else:
                self.staging_logger.warning(f"Level 2 MISS: entry_time={entry_time}, premium_diff=₹{premium_diff:.2f}")
                self.state["level_2_accurate_entries"] = 0
                
            if self.state["level_2_accurate_entries"] >= 10:
                self.state["current_level"] = 3
                self.staging_logger.info("⭐ LEVEL UP → Level 3 (Risk Management)")
                level_up = True
                
        elif lvl == 3:
            sl_exits = metrics.get("sl_exits", [])
            for sl in sl_exits:
                if sl.get("slippage", 999) < 2.0:
                    self.state["level_3_clean_sl_exits"] += 1
                    self.staging_logger.info(f"Level 3 Risk: {self.state['level_3_clean_sl_exits']}/5 clean SL exits")
                else:
                    self.staging_logger.warning(f"Level 3 FAIL: slippage=₹{sl.get('slippage', 0):.2f}")
                    
            if self.state["level_3_clean_sl_exits"] >= 5:
                self.state["current_level"] = 4
                self.state["level_4_start_date"] = today_str
                self.state["level_4_wins"] = 0
                self.state["level_4_total"] = 0
                self.state["level_4_net_pnl"] = 0.0
                self.staging_logger.info("⭐ LEVEL UP → Level 4 (Profitability)")
                level_up = True
                
        elif lvl == 4:
            daily_pnl = metrics.get("daily_pnl", 0.0)
            self.state["level_4_total"] += 1
            self.state["level_4_net_pnl"] += daily_pnl
            if daily_pnl > 0:
                self.state["level_4_wins"] += 1
                
            total = self.state["level_4_total"]
            wins = self.state["level_4_wins"]
            net = self.state["level_4_net_pnl"]
            win_rate = (wins / total * 100) if total > 0 else 0
            
            self.staging_logger.info(f"Level 4 Profit: Day {total}/15, Win Rate={win_rate:.1f}%, Net PnL=₹{net:.2f}")
            
            if total >= 15:
                if win_rate >= 55 and net > 0:
                    self.state["current_level"] = 5
                    self.staging_logger.info("🎓 LEVEL UP → Level 5 (GRADUATION! Manual UPSTOX unlock available)")
                    level_up = True
                else:
                    self.staging_logger.warning(f"Level 4 FAILED after 15 days: WR={win_rate:.1f}%, PnL=₹{net:.2f}. Resetting.")
                    self.state["level_4_start_date"] = today_str
                    self.state["level_4_wins"] = 0
                    self.state["level_4_total"] = 0
                    self.state["level_4_net_pnl"] = 0.0

        # Reset today's metrics for next day
        self.state["today_metrics"] = {}
        self.state["last_processed_date"] = today_str
        self.save_staging_state()
        return level_up
