"""
Centralized Configuration for Project Monie (Indian Markets Edition)
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Broker Selection: "SHOONYA", "UPSTOX", or "PAPER"
    BROKER = os.getenv("BROKER", "PAPER") # Default to PAPER for safety
    USE_WEBSOCKET = True                  # Set to True to use Event-Driven WS, False for 3s Polling
    PAPER_DATA_SOURCE = "UPSTOX"          # "SHOONYA" or "UPSTOX" for live data in paper mode
    
    # Shoonya Credentials
    SHOONYA_USER_ID = os.getenv("SHOONYA_USER_ID")
    SHOONYA_PASSWORD = os.getenv("SHOONYA_PASSWORD")
    SHOONYA_TOTP_SECRET = os.getenv("SHOONYA_TOTP_SECRET")
    SHOONYA_VENDOR_CODE = os.getenv("SHOONYA_VENDOR_CODE")
    SHOONYA_API_KEY = os.getenv("SHOONYA_API_KEY")
    SHOONYA_IMEI = os.getenv("SHOONYA_IMEI", "123456789012345")
    
    # Upstox Credentials
    UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY")
    UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET")
    UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI")
    UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN") # For manual token entry
    
    # Risk Management
    CAPITAL = float(os.getenv("CAPITAL", "50000"))  # Trading Capital
    MAX_DAILY_LOSS_PCT = 0.02  # 2% of Capital
    MAX_DAILY_LOSS = CAPITAL * MAX_DAILY_LOSS_PCT
    
    # Black Swan Safety
    ENABLE_BLACK_SWAN_GUARD = True
    MAX_GAP_PCT = 0.015       # 1.5% Pre-market Gap
    MAX_INTRADAY_ROC = 0.01   # 1% Move in 5 mins (Flash Crash)
    MAX_VIX = 30.0            # Don't trade if VIX > 30
    STRADDLE_TIME = "09:23"
    STRADDLE_EXIT_TIME = "15:15"
    STOP_LOSS_PCT_PER_LEG = 0.25  # 25% SL on each leg
    
    # Strategy Mode
    USE_HEDGES = False            # Set True for Iron Fly (Safety), False for Straddle (Max Profit)
    HEDGE_DIST = 200              # Buy OTM Wings 200 points away (Iron Fly)
    
    # Output Files
    METRICS_FILE = "execution_metrics.csv"  # OMS execution latency ledger
    LOG_FILE = "trades.csv"                 # Paper trading log
    
    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
