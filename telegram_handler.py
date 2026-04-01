"""
Telegram Handler — Async message dispatch, command processing, and daily reports.
Integrated with: Logger primitive, EventBus (for emergency commands).
"""
import requests
import time
import threading
import queue
import os
import json
import pandas as pd
import datetime
from config import Config
from core.logger import get_logger

logger = get_logger(__name__)


class TelegramHandler:
    def __init__(self, token=None, chat_id=None):
        _token = token or Config.TELEGRAM_TOKEN
        _chat_id = chat_id or Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{_token}" if _token else None
        self.chat_id = _chat_id
        self.last_update_id = 0
        self.running = True
        self.msg_queue = queue.Queue()
        self.token_updated_today = False  # Tracks if /token was sent today
        
        # References injected after construction by main.py
        self.event_bus = None
        self.orchestrator = None
        self.risk_manager = None
        self.broker = None

    def inject_dependencies(self, event_bus=None, orchestrator=None, risk_manager=None, broker=None):
        """Called by main.py after all components are constructed."""
        self.event_bus = event_bus
        self.orchestrator = orchestrator
        self.risk_manager = risk_manager
        self.broker = broker

    def send_message(self, message):
        """Asynchronously queues a message to the user."""
        if not self.base_url or not self.chat_id:
            return
        self.msg_queue.put(message)

    def _message_dispatcher(self):
        """Background thread that sends queued messages over the network."""
        while self.running:
            try:
                raw_msg = self.msg_queue.get(timeout=1)
                
                # Automatically prepend a timestamp to every outgoing alert
                timestamp = datetime.datetime.now().strftime("[%X]")
                formatted_msg = f"⏱️ `{timestamp}`\n{raw_msg}"
                
                url = f"{self.base_url}/sendMessage"
                payload = {"chat_id": self.chat_id, "text": formatted_msg, "parse_mode": "Markdown"}
                
                # Retry send with backoff (network can flake)
                for attempt in range(3):
                    try:
                        # Increased timeout to 10. Telegram API sometimes takes >5s.
                        requests.post(url, json=payload, timeout=10)
                        break
                    except requests.exceptions.RequestException as e:
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                        else:
                            logger.error(f"Telegram send failed after 3 attempts")
                
                self.msg_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Telegram Async Send Error: {e}")

    def get_updates(self):
        """Polls for new messages (commands)."""
        url = f"{self.base_url}/getUpdates"
        params = {
            "offset": self.last_update_id + 1,
            "timeout": 30
        }
        try:
            response = requests.get(url, params=params, timeout=35)
            return response.json()
        except Exception:
            return None

    def calculate_pnl(self):
        """Reads trades.csv and calculates profit."""
        try:
            log_file = getattr(Config, 'LOG_FILE', 'trades.csv')
            if not os.path.exists(log_file):
                return "No trades yet."
                
            df = pd.read_csv(log_file)
            if df.empty:
                return "No trades yet."
            
            current_balance = float(df.iloc[-1]['Balance'])
            initial_balance = float(getattr(Config, 'CAPITAL', 50000.0))
            pnl = current_balance - initial_balance
            pnl_pct = (pnl / initial_balance) * 100
            
            emoji = "🤑" if pnl >= 0 else "📉"
            return (
                f"{emoji} **PnL Report**\n"
                f"💰 Balance: ₹{current_balance:.2f}\n"
                f"📈 Profit: ₹{pnl:.2f} ({pnl_pct:.2f}%)"
            )
        except Exception:
            return "Could not read trade history."

    def send_daily_report(self):
        """Sends a consolidated daily report."""
        report = self.calculate_pnl()
        self.send_message(f"📅 **Daily Summary**\n{report}")

    def handle_commands(self):
        """Main loop for the bot thread."""
        logger.info("Telegram Bot Listening...")
        while self.running:
            updates = self.get_updates()
            if updates and "result" in updates:
                for update in updates["result"]:
                    self.last_update_id = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        
                        try:
                            self._dispatch_command(text)
                        except Exception as e:
                            logger.error(f"Telegram command error: {e}")
                            self.send_message(f"❌ Command error: {e}")
            
            time.sleep(1)

    def _dispatch_command(self, text: str):
        """Routes incoming Telegram commands to handlers."""
        if text == "/profit":
            report = self.calculate_pnl()
            self.send_message(report)
            
        elif text == "/ping":
            self.send_message("🏓 Pong! I am running. Waiting for trades...")
            
        elif text == "/kill":
            self._handle_kill()
            
        elif text == "/bus":
            self._handle_bus_stats()
            
        elif text.startswith("/token "):
            self._handle_token_update(text)
            
        elif text == "/status":
            self._handle_status()
            
        elif text == "/resume":
            self._handle_resume()
            
        elif text == "/logs":
            self._handle_logs()
            
        elif text == "/start":
            self.send_message("👋 I am Monie! Commands:\n/status — live trades\n/profit — ledger\n/token — auth Upstox\n/kill — emergency halt\n/resume — manual unkill\n/bus — event bus health\n/logs — tail live terminal")

    def _handle_logs(self):
        """Fetches the last 15 lines of the system journal directly from the OS."""
        self.send_message("⏳ Fetching live terminal logs from EC2...")
        import subprocess
        try:
            # The ubuntu user is in the adm group, giving read access to journalctl natively.
            result = subprocess.run(
                ["journalctl", "-u", "monie", "-n", "15", "--no-pager"], 
                capture_output=True, text=True, timeout=10
            )
            logs = result.stdout.strip()
            if not logs:
                logs = "Logs empty or required sudo."
            
            # Truncate to safely fit within Telegram's max message limit
            if len(logs) > 3500:
                logs = "..." + logs[-3500:]
                
            self.send_message(f"💻 **Live Terminal Output**\n```\n{logs}\n```")
        except Exception as e:
            self.send_message(f"⚠️ Failed to fetch logs: {e}")

    def _handle_kill(self):
        """Emergency remote kill switch — liquidates everything and trips circuit breaker."""
        kill_msg = "🔴 **EMERGENCY REMOTE KILL TRIGGERED**\nLiquidating ALL positions and halting trading."
        logger.critical(kill_msg)
        self.send_message(kill_msg)
        
        if self.risk_manager:
            self.risk_manager.is_circuit_breaker_tripped = True
        
        if self.orchestrator:
            try:
                self.orchestrator.square_off_all(reason_msg=kill_msg)
                self.send_message("✅ All positions squared off. Bot is now HALTED.")
            except Exception as e:
                self.send_message(f"⚠️ Kill executed but square-off had errors: {e}")
        else:
            self.send_message("⚠️ Orchestrator not available. Circuit breaker tripped only.")

    def _handle_resume(self):
        """Manually clears the circuit breaker and guard after a /kill or crash."""
        if self.risk_manager:
            self.risk_manager.reset_circuit_breaker()
            self.send_message("🟢 **RESUMED**\nCircuit breaker and Black Swan Guard reset. The bot will now take fresh signals and resume trading.")
        else:
            self.send_message("⚠️ Risk Manager not available to resume.")

    def _handle_bus_stats(self):
        """Returns EventBus health metrics."""
        if self.event_bus:
            stats = self.event_bus.get_stats()
            msg = (
                f"📊 **Event Bus Health**\n"
                f"Queue: {stats['queue_depth']}/{stats['queue_max']}\n"
                f"Processed: {stats['events_processed']:,}\n"
                f"Dropped: {stats['events_dropped']}\n"
                f"Subscribers: {stats['subscriber_count']}"
            )
            self.send_message(msg)
        else:
            self.send_message("⚠️ EventBus not available.")

    def _handle_token_update(self, text: str):
        """Handles /token command to update Upstox access token.
        Works at ANY time — before market, during market, or after market.
        Hot-reloads the broker session so no restart is needed.
        """
        new_token = text.split(" ", 1)[1].strip()
        try:
            # 1. Write to .env for persistence across restarts
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            with open(env_path, 'r') as file:
                lines = file.readlines()
            
            updated = False
            for i in range(len(lines)):
                if lines[i].startswith("UPSTOX_ACCESS_TOKEN="):
                    lines[i] = f"UPSTOX_ACCESS_TOKEN={new_token}\n"
                    updated = True
                    break
            
            if not updated:
                lines.append(f"\nUPSTOX_ACCESS_TOKEN={new_token}\n")
            
            with open(env_path, 'w') as file:
                file.writelines(lines)
            
            # 2. Update in-memory Config
            Config.UPSTOX_ACCESS_TOKEN = new_token
            self.token_updated_today = True
            
            # 3. Hot-reload broker session (no restart needed)
            # Must propagate to the ACTUAL Upstox broker, not just the PaperBroker wrapper
            reload_msg = ""
            if self.broker:
                # Find the real Upstox data source (PaperBroker wraps it as .data_source)
                actual_broker = getattr(self.broker, 'data_source', self.broker)
                if actual_broker and hasattr(actual_broker, 'config'):
                    actual_broker.config.UPSTOX_ACCESS_TOKEN = new_token
                    if actual_broker.authenticate():
                        reload_msg = "\n🔄 Upstox API client re-authenticated!"
                        try:
                            if hasattr(actual_broker, 'ws_client') and actual_broker.ws_client:
                                actual_broker.ws_client.stop()
                                
                            if hasattr(actual_broker, 'start_websocket'):
                                import time
                                actual_broker.start_websocket(on_error_callback=lambda e: logger.error(f"WS Error: {e}"))
                                time.sleep(2)
                                actual_broker.subscribe(["NSE|Nifty 50", "NSE|INDIA VIX", "NSE|Nifty Bank"])
                                reload_msg += "\n📡 WebSocket restarted and tracking."
                        except Exception as we:
                            reload_msg += f"\n⚠️ WebSocket restart error: {we}"
                    else:
                        reload_msg = "\n⚠️ Token saved but Upstox re-auth failed."
                # Also update the PaperBroker's own config reference
                if hasattr(self.broker, 'config'):
                    self.broker.config.UPSTOX_ACCESS_TOKEN = new_token
            
            self.send_message(f"✅ Upstox Token Received & Updated!\nThe Bot will use this token for all new requests today.{reload_msg}")
            logger.info("New Upstox token injected via Telegram.")
        except Exception as e:
            self.send_message(f"❌ Failed to update token: {e}")

    def _handle_status(self):
        """Returns comprehensive system health status."""
        status_msg = "🤖 **System Health: ONLINE**\n"
        
        # Risk Manager info
        if self.risk_manager:
            cb = '🔴 TRIPPED' if self.risk_manager.is_circuit_breaker_tripped else '🟢 OK'
            guard = '🔴 ACTIVE' if self.risk_manager.guard_active else '🟢 Normal'
            
            # Extract fast flash crash buffer size
            buffer_size = 0
            if hasattr(self.risk_manager.guard, '_price_buffer'):
                buffer_size = len(self.risk_manager.guard._price_buffer)
                
            status_msg += f"🛡️ Circuit Breaker: {cb}\n"
            status_msg += f"⚡ Risk Guard: {guard}\n"
            status_msg += f"⏱️ Flash Monitor: 🟢 Active ({buffer_size} ticks buffered)\n"
            status_msg += f"📊 Daily PnL: ₹{self.risk_manager.current_pnl:.2f}\n"
            status_msg += f"📈 Trades Today: {self.risk_manager.daily_trades}\n\n"
        
        # WebSocket connectivity
        if self.broker:
            ws = getattr(self.broker, 'ws_client', None)
            if ws is None:
                ws_broker = getattr(self.broker, 'data_source', None)
                if ws_broker:
                    ws = getattr(ws_broker, 'ws_client', None)
            if ws:
                ws_status = '🟢 Connected' if ws.is_connected else '🔴 Disconnected'
                cached = len(ws.price_cache)
                status_msg += f"📡 WebSocket: {ws_status} ({cached} symbols cached)\n"
            else:
                status_msg += "📡 WebSocket: ⚪ Not started (REST mode)\n"
        
        # EventBus health
        if self.event_bus:
            stats = self.event_bus.get_stats()
            status_msg += f"🔄 EventBus: {stats['events_processed']:,} processed, {stats['events_dropped']} dropped\n\n"
        
        # Active trade legs
        if os.path.exists("bot_state.json"):
            try:
                with open("bot_state.json", 'r') as f:
                    state = json.load(f)
                if state.get("traded_today"):
                    status_msg += "✅ **Trades:** Executed Today\n\n**Live Legs:**\n"
                    legs = state.get("active_legs", {})
                    active_count = 0
                    for key, leg in legs.items():
                        if leg and isinstance(leg, dict) and leg.get("active"):
                            active_count += 1
                            status_msg += f"👉 {leg.get('symbol')}\nEntry: ₹{leg.get('entry_price',0):.1f} | SL: ₹{leg.get('sl_price',0):.1f}\n"
                    if active_count == 0:
                        status_msg += "All positions have hit Stop Loss or Liquidation!"
                else:
                    status_msg += "⏳ **Trades:** Waiting for signal or schedule...\n"
            except Exception:
                status_msg += "⚠️ Could not read state.\n"
        else:
            status_msg += "⏳ **Trades:** No state file (waiting for trades).\n"
        self.send_message(status_msg)

    def start(self):
        """Starts the local polling thread and the async dispatch queue."""
        t1 = threading.Thread(target=self.handle_commands)
        t1.daemon = True
        t1.start()
        
        t2 = threading.Thread(target=self._message_dispatcher)
        t2.daemon = True
        t2.start()
