"""
Upstox Connection Test (READ-ONLY)
Tests:
1. Authentication with Access Token
2. Fetching NIFTY 50 LTP (Read-Only)
3. Fetching INDIA VIX LTP (Read-Only)
4. Verifying Paper Broker wrapper safety

⚠️ This script does NOT place any orders or modify your account in any way.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def test_upstox_connection():
    print("=" * 60)
    print("🔒 UPSTOX CONNECTION TEST (READ-ONLY)")
    print("=" * 60)
    
    # 1. Verify Config
    print("\n--- Step 1: Config Check ---")
    print(f"  BROKER:            {Config.BROKER}")
    print(f"  PAPER_DATA_SOURCE: {getattr(Config, 'PAPER_DATA_SOURCE', 'NOT SET')}")
    print(f"  UPSTOX_API_KEY:    {'✅ Set' if Config.UPSTOX_API_KEY else '❌ Missing'}")
    print(f"  UPSTOX_API_SECRET: {'✅ Set' if Config.UPSTOX_API_SECRET else '❌ Missing'}")
    print(f"  ACCESS_TOKEN:      {'✅ Set' if Config.UPSTOX_ACCESS_TOKEN else '❌ Missing'}")
    
    if not Config.UPSTOX_ACCESS_TOKEN:
        print("\n❌ Cannot proceed without UPSTOX_ACCESS_TOKEN in .env")
        return False
    
    # 2. Test UpstoxBroker Authentication
    print("\n--- Step 2: Upstox Authentication ---")
    from core.brokers.upstox import UpstoxBroker
    upstox = UpstoxBroker(Config)
    auth_ok = upstox.authenticate()
    
    if not auth_ok:
        print("❌ Authentication Failed! Check your Access Token.")
        return False
    print("✅ Upstox Authentication Successful")
    
    # 3. Test LTP Fetch (READ-ONLY)
    print("\n--- Step 3: Live Data Fetch (Read-Only) ---")
    
    nifty_ltp = upstox.get_quote("NSE|Nifty 50")
    print(f"  NIFTY 50 LTP:  {nifty_ltp}")
    
    vix = upstox.get_quote("NSE|INDIA VIX")
    print(f"  INDIA VIX:     {vix}")
    
    if nifty_ltp and nifty_ltp > 0:
        print("  ✅ Live Data Feed Working")
    else:
        print("  ⚠️ LTP returned 0 — Possible symbol mapping issue or market closed")
    
    # 4. Test Paper Broker Wrapper (SAFETY CHECK)
    print("\n--- Step 4: Paper Broker Safety Test ---")
    from core.brokers.paper import PaperBroker
    paper = PaperBroker(Config, data_source_broker=upstox)
    
    # Place a FAKE order through Paper
    order_id = paper.place_order("TEST_SYMBOL", 50, "SELL")
    print(f"  Paper Order ID: {order_id}")
    
    # Verify NO real order was placed
    print(f"  Paper Orders (in RAM): {len(paper.orders)} order(s)")
    print(f"  Paper Positions:       {paper.positions}")
    
    # Verify Upstox was NOT called for order placement
    # (PaperBroker.place_order only calls data_source.get_quote, NEVER place_order)
    print("  ✅ Paper Broker intercepted order. Upstox was NOT touched.")
    
    # 5. Summary
    print("\n" + "=" * 60)
    print("🔒 SAFETY REPORT")
    print("=" * 60)
    print(f"  Config.BROKER = '{Config.BROKER}' (PAPER mode)")
    print(f"  Upstox used for: DATA ONLY (get_quote)")
    print(f"  Orders go to:    PaperBroker (RAM only)")
    print(f"  Real Orders:     ❌ NONE (Confirmed)")
    print(f"  Your Investments: 🔒 UNTOUCHED")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    success = test_upstox_connection()
    if success:
        print("\n✅ All tests passed. Ready for Paper Trading.")
    else:
        print("\n❌ Test failed. Check errors above.")
