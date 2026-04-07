"""
Project Monie - Main Application Entry Point
Orchestrates: EventBus -> Broker -> RiskManager -> OMS -> Strategy
Non-blocking async main loop with health checks run in executor.
Dynamic capital sync from Upstox wallet at boot and EOD.
"""
import asyncio
import time
import os
import socket
import schedule
import datetime

# Global Network Failsafe
socket.setdefaulttimeout(10.0)

from config import Config
from core.brokers.shoonya import ShoonyaBroker
from core.risk_manager import RiskManager
from core.strategy_orchestrator import StrategyOrchestrator
from strategies.intraday_straddle import IntradayShortStraddle
from strategies.volatility_harvester import VolatilityHarvester
from strategies.theta_crusher import ThetaCrusher
from strategies.expiryday_scalper import ExpirydayScalper
from strategies.afternoon_momentum import AfternoonMomentumScalper
from telegram_handler import TelegramHandler
from core.logger import get_logger

from core.event_bus import EventBus
from core.events import CleanTickEvent
from core.oms import OrderManagementSystem
from core.staging_manager import StagingManager
from core.state_manager import StateManager

logger = get_logger(__name__)

# Health check interval (seconds)
HEALTH_CHECK_INTERVAL = 30

# Bounded thread pool for health check REST calls.
# Prevents thread exhaustion from timed-out API calls over multi-day uptime.
from concurrent.futures import ThreadPoolExecutor
_health_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health")


def get_broker_instance(config, event_bus):
    """Factory function to return the appropriate broker instance."""
    try:
        if config.BROKER == "SHOONYA":
            return ShoonyaBroker(config)
            
        elif config.BROKER == "PAPER":
            logger.info("📝 Starting in PAPER TRADING Mode...")
            data_broker = None
            source_name = getattr(config, 'PAPER_DATA_SOURCE', 'SHOONYA')
            
            if source_name == "SHOONYA":
                logger.info("   Using SHOONYA for Live Data...")
                data_broker = ShoonyaBroker(config)
            elif source_name == "UPSTOX":
                logger.info("   Using UPSTOX for Live Data...")
                from core.brokers.upstox import UpstoxBroker
                data_broker = UpstoxBroker(config, event_bus=event_bus)
            
            if data_broker:
                if not data_broker.authenticate():
                     logger.warning(f"⚠️ {source_name} Login Failed. Paper mode will use Mock Data.")
                     data_broker = None
                else:
                     logger.info(f"✅ {source_name} Connected for Live Quotes.")
            
            from core.brokers.paper import PaperBroker
            return PaperBroker(config, data_source_broker=data_broker)
            
        elif config.BROKER == "UPSTOX":
            from core.brokers.upstox import UpstoxBroker
            return UpstoxBroker(config, event_bus=event_bus)
            
        else:
            logger.error(f"❌ Unknown Broker: {config.BROKER}")
            return None
    except Exception as e:
        logger.error(f"❌ Error initializing broker: {e}")
        return None


def sync_capital(broker, risk_manager, config, telegram=None):
    """
    Syncs RiskManager capital from actual Upstox wallet balance.
    Handles deposits, withdrawals, and profit compounding automatically.
    Falls back to Config.CAPITAL if margin API fails.
    """
    if not hasattr(broker, 'get_available_margin'):
        return  # Non-Upstox brokers don't support this
    
    wallet_balance = broker.get_available_margin()
    if wallet_balance <= 0:
        logger.warning("⚠️ Could not fetch wallet balance. Using Config.CAPITAL as fallback.")
        return
    
    old_capital = risk_manager.capital
    delta = wallet_balance - old_capital
    
    risk_manager.capital = wallet_balance
    risk_manager.max_daily_loss = wallet_balance * config.MAX_DAILY_LOSS_PCT
    
    delta_emoji = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
    msg = (
        f"💰 **Capital Sync**\n"
        f".env Capital: ₹{config.CAPITAL:,.0f}\n"
        f"Wallet Balance: ₹{wallet_balance:,.0f}\n"
        f"{delta_emoji} Delta: ₹{delta:+,.0f}\n"
        f"New Daily Loss Limit: ₹{risk_manager.max_daily_loss:,.0f}"
    )
    logger.info(msg)
    if telegram:
        telegram.send_message(msg)


async def validate_token(broker, telegram):
    """
    Validates that the Upstox token actually works by making a lightweight API call.
    Retries every 5 minutes until 09:30 to give user time to send /token.
    """
    loop = asyncio.get_running_loop()
    max_retry_time = datetime.time(9, 30)
    
    while True:
        try:
            # Lightweight validation call
            quote = await loop.run_in_executor(None, broker.get_quote, "NSE|Nifty 50")
            if quote and quote > 0:
                logger.info(f"✅ Token validated — Nifty 50 LTP: ₹{quote:.2f}")
                return True
        except Exception:
            pass
        
        now = datetime.datetime.now().time()
        if now >= max_retry_time:
            logger.error("❌ Token validation failed after retries. Bot may not trade today.")
            if telegram:
                telegram.send_message("❌ **TOKEN EXPIRED or INVALID!**\nSend `/token <your_upstox_token>` NOW to trade today.")
            return False
        
        logger.warning("⚠️ Token validation failed. Retrying in 5 minutes...")
        if telegram:
            telegram.send_message("⚠️ Token seems expired. Retrying in 5 min.\nSend `/token <your_token>` to fix.")
        await asyncio.sleep(300)  # 5 minutes


async def _run_health_check(broker, risk_manager, orchestrator, telegram):
    """
    Non-blocking health check. Runs broker REST calls in a dedicated executor
    to prevent freezing the EventBus. Uses a bounded thread pool to avoid
    exhaustion from timed-out calls over multi-day uptime.
    """
    loop = asyncio.get_running_loop()
    try:
        # Use the module-level bounded executor instead of the default (prevents thread leak)
        current_pnl = await asyncio.wait_for(
            loop.run_in_executor(_health_executor, broker.get_pnl), timeout=8.0)
        nifty_ltp = await asyncio.wait_for(
            loop.run_in_executor(_health_executor, broker.get_quote, "NSE|Nifty 50"), timeout=8.0)
        india_vix = await asyncio.wait_for(
            loop.run_in_executor(_health_executor, broker.get_quote, "NSE|INDIA VIX"), timeout=8.0)
        
        # Market health
        is_healthy, status = risk_manager.check_market_health(nifty_ltp, None, india_vix)
        if risk_manager.guard.check_stale_quotes(nifty_ltp):
            is_healthy = False
            status = "🛑 Market Heartbeat Lost"
        if not is_healthy:
            logger.warning(f"⚠️ {status} - Halting Trading!")
        
        # PnL circuit breaker
        allowed, status = risk_manager.update_pnl(current_pnl)
        
        if not allowed and not getattr(risk_manager, 'alert_sent', False):
            circuit_breaker_msg = f"🛡️ **ACCOUNT CIRCUIT BREAKER TRIPPED**\n\n{status}\n\nLiquidating immediately!"
            logger.critical(circuit_breaker_msg)
            if telegram: telegram.send_message(circuit_breaker_msg)
            risk_manager.alert_sent = True
            if risk_manager.is_circuit_breaker_tripped:
                orchestrator.square_off_all(reason_msg=circuit_breaker_msg)
                
    except asyncio.TimeoutError:
        logger.warning("Health check timed out (API unresponsive for 8s)")
    except Exception as e:
        logger.error(f"Health check failed (non-fatal): {type(e).__name__}: {e}")

def _fast_flash_crash_monitor(event, risk_manager, orchestrator, telegram, broker):
    """EventBus hook for instant wartime flash crash detection."""
    if hasattr(event, "symbol") and getattr(event, "symbol") == "NSE|Nifty 50":
        # Pull latest VIX from broker cache (since this is firing sub-millisecond on every trade)
        try:
            vix = broker.get_cached_quote("INDIA VIX")
            if not vix or vix <= 0:
                 vix = getattr(risk_manager, 'dynamic_vix_proxy', 25.0)
        except Exception:
            vix = getattr(risk_manager, 'dynamic_vix_proxy', 25.0)
        
        status = risk_manager.guard.check_flash_crash_rolling(event.ltp, current_vix=vix)
        
        if status == "VELOCITY_SHOCK":
            if not getattr(risk_manager, 'alert_sent', False):
                risk_manager.is_circuit_breaker_tripped = True
                msg = f"🛡️ **OMEGA VELOCITY SHOCK TRIPPED**\n\nAbsolute Vertical Move (>0.5% in 5s). Liquidating instantly to frontrun cascading stops!"
                logger.critical(msg)
                if telegram: telegram.send_message(msg)
                risk_manager.alert_sent = True
                orchestrator.square_off_all(reason_msg=msg)
                
        elif status == "HEDGE_MODE" and not risk_manager.in_hedge_mode:
            risk_manager.in_hedge_mode = True
            msg = f"⚠️ **OMNI-MARKET RESILIENCY**\n\nStructural VIX limits breached (3-Min). Entering Hedge Mode: No new entries. Trailing stops severely tightened."
            logger.critical(msg)
            if telegram: telegram.send_message(msg)
            orchestrator.activate_hedge_mode()


async def main_async():
    logger.info("Starting Monie Bot (Event-Driven Edition)...")
    
    # 0. Firmware Lock (Staging Pipeline)
    staging_manager = StagingManager()
    current_level = staging_manager.get_current_level()
    if Config.BROKER == "UPSTOX" and not staging_manager.is_live_trading_allowed():
        lock_msg = f"🔒 FIRMWARE FASTENED: Live capital locked until Level 5. Current: {current_level}/5. Forcing PAPER mode."
        logger.warning(lock_msg)
        Config.BROKER = "PAPER"

    telegram = TelegramHandler()
    telegram.start()
    telegram.send_message("🤖 Monie Bot Reactive Engine initialized. Booting...")
    if Config.BROKER == "PAPER":
         telegram.send_message(f"🔒 Failsafe Active. Tracking Stage Level {current_level}/5. Live capital restricted.")

    # 1. Start Core Primitives
    event_bus = EventBus(maxsize=10000)
    event_bus.start()
    
    broker = get_broker_instance(Config, event_bus)
    if not broker:
        telegram.send_message("❌ Invalid Broker Configuration. Exiting.")
        return

    if not broker.authenticate():
        telegram.send_message("❌ Broker Login Failed! Check credentials.")
        return
    telegram.send_message(f"✅ Logged into {Config.BROKER}")

    # 2. Token validation (non-blocking, retries until 09:30)
    token_valid = await validate_token(broker, telegram)
    if not token_valid:
        logger.warning("Proceeding with potentially expired token. Strategies may fail.")

    # 3. Dynamic Capital Sync from actual Upstox wallet
    risk_manager = RiskManager(max_daily_loss=Config.MAX_DAILY_LOSS, capital=Config.CAPITAL)
    sync_capital(broker, risk_manager, Config, telegram)
    
    # 4. Start Order Management System (OMS)
    oms = OrderManagementSystem(event_bus, broker, risk_manager)
    await oms.reconcile_with_broker()  # Detect orphaned positions from prior crashes
    
    # 5. Start State Memory
    state_manager = StateManager()
    
    # 6. Wire Strategies to Orchestrator
    common_args = dict(broker=broker, risk_manager=risk_manager, event_bus=event_bus, config=Config,
                       state_manager=state_manager, telegram=telegram, staging_manager=staging_manager)
    
    strategies = [
        IntradayShortStraddle(**common_args),
        VolatilityHarvester(**common_args),
        ThetaCrusher(**common_args),
        ExpirydayScalper(**common_args),
        AfternoonMomentumScalper(**common_args),
    ]
    orchestrator = StrategyOrchestrator(strategies, event_bus, telegram=telegram)

    # 6.5 Wire up ultra-fast Omni-Market Flash Crash monitor
    event_bus.subscribe(CleanTickEvent, lambda e: _fast_flash_crash_monitor(e, risk_manager, orchestrator, telegram, broker))
    
    # 7. Inject dependencies into Telegram for /kill and /bus commands
    telegram.inject_dependencies(
        event_bus=event_bus,
        orchestrator=orchestrator,
        risk_manager=risk_manager,
        broker=broker
    )
    
    # 8. Start Data Feed
    # If using PaperBroker, the actual data feed is wrapped in 'data_source'
    actual_data_broker = getattr(broker, 'data_source', broker) or broker
    if hasattr(actual_data_broker, 'start_websocket'):
        actual_data_broker.start_websocket(on_error_callback=lambda e: logger.error(f"WS Error: {e}"))
        # Allow WS connection to establish before subscribing (V3 SDK connects async)
        await asyncio.sleep(2)
        # Crucial kickstart: Subscribe to baseline indices to start driving the EventBus
        actual_data_broker.subscribe(["NSE|Nifty 50", "NSE|INDIA VIX", "NSE|Nifty Bank"])

    logger.info("⏳ Waiting for Market Hours... (Event Loop Active)")
    
    def is_trading_day():
        return datetime.datetime.now().weekday() < 5

    def eod_evaluation():
        if not is_trading_day(): return
        daily_pnl = broker.get_pnl()
        staging_manager.record_daily_pnl(daily_pnl)
        if staging_manager.evaluate_daily_performance({}):
            telegram.send_message(f"⭐⭐ LEVEL UP! Bot advanced to Level {staging_manager.get_current_level()}/5")
        
        # Auto-compound: sync capital from wallet after EOD so tomorrow's sizing reflects today's profit/loss
        sync_capital(broker, risk_manager, Config, telegram)
        
        telegram.send_message(f"🔔 Market Closed! Day PnL: ₹{daily_pnl:.2f}. Staging Level: {staging_manager.get_current_level()}/5")
        
        # Reset token flag for next day
        telegram.token_updated_today = False
        
    def token_reminder():
        if is_trading_day() and not telegram.token_updated_today:
            telegram.send_message("⚠️ Remember to update your Upstox Token today!\nReply with: `/token <your_token>`")
    
    schedule.every().day.at("09:00").do(token_reminder)
    schedule.every().day.at("09:14").do(lambda: risk_manager.reset_daily_stats() if is_trading_day() else None)
    schedule.every().day.at("09:15").do(lambda: telegram.send_message("🔔 Market Open!") if is_trading_day() else None)
    schedule.every().day.at("15:30").do(eod_evaluation)
    
    def memory_cleanup():
        try:
            import shutil, gzip
            total, used, free = shutil.disk_usage("/")
            free_mb = free // (1024 * 1024)
            if free_mb < 200:
                log_file = "logs/staging_journal.log"
                if os.path.exists(log_file) and os.path.getsize(log_file) > 100000:
                    archive = f"logs/staging_archive_{datetime.datetime.now().strftime('%Y%m%d')}.gz"
                    with open(log_file, 'rb') as f_in, gzip.open(archive, 'wb') as f_out:
                        f_out.write(f_in.read())
                    with open(log_file, 'w') as f: f.write("")
                    telegram.send_message(f"🗜️ Logs archived ({free_mb}MB free).")
        except Exception as e:
            logger.error(f"⚠️ Memory cleanup error: {e}")
            
    schedule.every().day.at("15:45").do(memory_cleanup)

    last_health_check = 0.0
    
    try:
        while True:
            schedule.run_pending()
            
            now = datetime.datetime.now()
            now_time = now.time()
            now_ts = time.time()
            
            # Health checks during market window, throttled to HEALTH_CHECK_INTERVAL
            if (datetime.time(9, 0) <= now_time <= datetime.time(15, 45) 
                and (now_ts - last_health_check) >= HEALTH_CHECK_INTERVAL):
                last_health_check = now_ts
                asyncio.create_task(_run_health_check(broker, risk_manager, orchestrator, telegram))
            
            # Yield control to the EventBus processing loop
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("\n🛑 Bot stopped (Async Cancelled).")
    except Exception as e:
        logger.critical(f"Critical Error: {e}", exc_info=True)
        if 'staging_manager' in locals(): staging_manager.log_critical_error(str(e))
        if telegram: telegram.send_message(f"❌ Critical Error: {e}")
    finally:
        event_bus.stop()
        telegram.send_message("🛑 Monie Bot shutdown complete.")


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")


if __name__ == "__main__":
    main()
