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

    def send_message(self, message, reply_markup=None):
        """Asynchronously queues a message to the user."""
        if not self.base_url or not self.chat_id:
            return
        self.msg_queue.put(('text', message, reply_markup))

    def send_document(self, filename, caption=None):
        """Asynchronously queues a document upload to the user."""
        if not self.base_url or not self.chat_id:
            return
        self.msg_queue.put(('document', filename, caption))

    def answer_callback_query(self, callback_id):
        """Acknowledges a callback query instantly."""
        if not self.base_url: return
        url = f"{self.base_url}/answerCallbackQuery"
        try:
            requests.post(url, json={"callback_query_id": callback_id}, timeout=5)
        except Exception as e:
            logger.error(f"Callback answer error: {e}")

    def _message_dispatcher(self):
        """Background thread that sends queued messages over the network."""
        while self.running:
            try:
                item = self.msg_queue.get(timeout=1)
                msg_type = item[0]
                
                if msg_type == 'text':
                    _, raw_msg, reply_markup = item
                    timestamp = datetime.datetime.now().strftime("[%X]")
                    formatted_msg = f"⏱️ `{timestamp}`\n{raw_msg}"
                    
                    url = f"{self.base_url}/sendMessage"
                    payload = {"chat_id": self.chat_id, "text": formatted_msg, "parse_mode": "Markdown"}
                    if reply_markup:
                        payload['reply_markup'] = reply_markup
                        
                    # Retry send with backoff
                    for attempt in range(3):
                        try:
                            requests.post(url, json=payload, timeout=10)
                            break
                        except requests.exceptions.RequestException as e:
                            if attempt < 2: time.sleep(2 ** attempt)
                            else: logger.error("Telegram send failed after 3 attempts")
                            
                elif msg_type == 'document':
                    _, filepath, caption = item
                    url = f"{self.base_url}/sendDocument"
                    if os.path.exists(filepath):
                        with open(filepath, 'rb') as doc:
                            payload = {"chat_id": self.chat_id}
                            if caption: payload["caption"] = caption
                            files = {"document": doc}
                            requests.post(url, data=payload, files=files, timeout=20)
                            
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

    def _is_authorized_update(self, update: dict) -> bool:
        """Accept commands only from the configured chat id."""
        expected_chat_id = str(self.chat_id) if self.chat_id is not None else None
        if not expected_chat_id:
            return True

        chat_id = None
        if "message" in update and "chat" in update["message"]:
            chat_id = update["message"]["chat"].get("id")
        elif "callback_query" in update and "message" in update["callback_query"]:
            chat_id = update["callback_query"]["message"].get("chat", {}).get("id")

        authorized = str(chat_id) == expected_chat_id
        if not authorized:
            logger.warning(f"Unauthorized Telegram command attempt from chat_id={chat_id}")
        return authorized

    def handle_commands(self):
        """Main loop for the bot thread."""
        logger.info("Telegram Bot Listening...")
        while self.running:
            updates = self.get_updates()
            if updates and "result" in updates:
                for update in updates["result"]:
                    self.last_update_id = update["update_id"]
                    if not self._is_authorized_update(update):
                        continue
                    
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        try:
                            self._dispatch_command(text)
                        except Exception as e:
                            logger.error(f"Telegram command error: {e}")
                            self.send_message(f"❌ Command error: {e}")
                            
                    elif "callback_query" in update:
                        query = update["callback_query"]
                        data = query.get("data", "")
                        callback_id = query.get("id")
                        self.answer_callback_query(callback_id)
                        try:
                            self._dispatch_command(data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
            
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

        elif text == "/resume":
            self._handle_resume()
            
        elif text == "/bus":
            self._handle_bus_stats()
            
        elif text.startswith("/token "):
            self._handle_token_update(text)
            
        elif text == "/status":
            self._handle_status()
            
        elif text == "/menu" or text == "/start":
            self._handle_menu()
            
        elif text == "/logs":
            self._handle_logs_menu()
            
        elif text == "/log_50":
            self._handle_logs(lines=50)
            
        elif text == "/log_file":
            self._handle_log_download()
            
        elif text.startswith("/log "):
            self._handle_log_by_date(text)
            

    def _handle_menu(self):
        """Sends the interactive command menu."""
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📊 Status", "callback_data": "/status"}, {"text": "💰 PnL", "callback_data": "/profit"}],
                [{"text": "🖥️ Logs Menu", "callback_data": "/logs"}, {"text": "📈 Event Bus", "callback_data": "/bus"}],
                [{"text": "🟢 Resume", "callback_data": "/resume"}, {"text": "🔴 KILL SWITCH", "callback_data": "/kill"}]
            ]
        }
        self.send_message("🤖 **Monie Institutional Console**\nSelect an action:", reply_markup=reply_markup)

    def _handle_logs_menu(self):
        """Interactive logs menu."""
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📄 Last 50 Lines", "callback_data": "/log_50"}],
                [{"text": "📅 Fetch by Date", "callback_data": "/log_date_help"}],
                [{"text": "📥 Download Full Log File", "callback_data": "/log_file"}]
            ]
        }
        self.send_message("🖥️ **Log Management Console**\nChoose an option:", reply_markup=reply_markup)

    def _handle_log_download(self):
        """Uploads the entire journalctl log as a file."""
        import subprocess
        try:
            self.send_message("⏳ Generating log file...")
            log_path = "/tmp/monie_full.log"
            subprocess.run(f"journalctl -u monie --no-pager > {log_path}", shell=True)
            self.send_document(log_path, caption="🖥️ Full System Log")
        except Exception as e:
            self.send_message(f"⚠️ Failed to generate log file: {e}")

    def _handle_logs(self, lines=15):
        """Fetches the last N lines of the system journal directly from the OS."""
        self.send_message(f"⏳ Fetching last {lines} lines...")
        import subprocess
        try:
            result = subprocess.run(
                ["journalctl", "-u", "monie", "-n", str(lines), "--no-pager"], 
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

    def _handle_log_by_date(self, text: str):
        """Fetches logs for a specific date (e.g. /log 2026-04-06)."""
        if text == "/log_date_help":
            self.send_message("📅 To fetch logs for a specific date, type:\n`/log YYYY-MM-DD`\n\nExample: `/log 2026-04-06`")
            return
            
        parts = text.split(" ")
        if len(parts) < 2:
            self.send_message("⚠️ Please provide a date. Format: `/log YYYY-MM-DD`")
            return
            
        date_str = parts[1].strip()
        self.send_message(f"⏳ Fetching logs for {date_str}...")
        
        import subprocess
        try:
            log_path = f"/tmp/monie_{date_str}.log"
            cmd = f'journalctl -u monie --since "{date_str} 00:00:00" --until "{date_str} 23:59:59" --no-pager > {log_path}'
            subprocess.run(cmd, shell=True)
            
            if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
                self.send_document(log_path, caption=f"📅 System Log: {date_str}")
            else:
                self.send_message(f"⚠️ No logs found for {date_str}.")
        except Exception as e:
            self.send_message(f"⚠️ Failed to generate log file: {e}")

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
            
            # Atomic write: temp file → os.replace() (prevents corruption on crash)
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(env_path),
                                              delete=False, suffix='.env.tmp') as tmp:
                tmp.writelines(lines)
                tmp_path = tmp.name
            os.replace(tmp_path, env_path)
            
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
        
        # Active trade legs — read from SQLite StateManager (not legacy JSON)
        try:
            from core.state_manager import StateManager
            sm = StateManager()
            traded = sm.state.get("traded_today", False)
            if traded:
                today_str = str(datetime.datetime.now().date())
                if sm.state.get("last_trade_date") == today_str:
                    status_msg += "✅ **Trades:** Executed Today\n\n**Live Legs:**\n"
                    legs = sm.state.get("active_legs", {})
                    active_count = 0
                    for key, leg in legs.items():
                        if leg and isinstance(leg, dict) and leg.get("active"):
                            active_count += 1
                            status_msg += f"👉 {leg.get('symbol')}\nEntry: ₹{leg.get('entry_price',0):.1f} | SL: ₹{leg.get('sl_price',0):.1f}\n"
                    if active_count == 0:
                        status_msg += "All positions have hit Stop Loss or Liquidation!"
                else:
                    status_msg += "⏳ **Trades:** Waiting for signal or schedule...\n"
            else:
                status_msg += "⏳ **Trades:** Waiting for signal or schedule...\n"
        except Exception:
            status_msg += "⚠️ Could not read state.\n"
        self.send_message(status_msg)

    def start(self):
        """Starts the local polling thread and the async dispatch queue."""
        t1 = threading.Thread(target=self.handle_commands)
        t1.daemon = True
        t1.start()
        
        t2 = threading.Thread(target=self._message_dispatcher)
        t2.daemon = True
        t2.start()
