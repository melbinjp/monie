"""
Live Execution Test: The 1-Lot "Penny" Test
---------------------------------------------
PURPOSE:
To verify that your Upstox API credentials, network connection, and execution logic 
can place REAL MONEY orders successfully, without risking your ₹50k capital.

HOW IT WORKS:
Instead of trading ATM options (which cost thousands of rupees), this script buys 
1 lot (25 qty) of a Far-OTM (Out of the Money) NIFTY option.
This option will cost roughly ₹1.00 - ₹2.00 per share.
Your MAXIMUM total risk is ₹50 to ₹100.

SAFETY MEASURES:
1. It buys the cheapest option it can find to test execution.
2. It waits for 5 seconds to confirm it appears in your Upstox Portfolio.
3. It immediately places a SELL order to square off the position.
4. Total time in the market: 5 seconds.
"""

import sys
import time
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from config import Config
from core.brokers.upstox import UpstoxBroker

def run_penny_test():
    print("=" * 60)
    print("🚨 LIVE MONEY PENNY TEST 🚨")
    print("=" * 60)
    
    if Config.BROKER != "UPSTOX":
        print(f"❌ Error: Config.BROKER is set to '{Config.BROKER}'.")
        print("You must set BROKER=UPSTOX in your .env file to run a Live Money test.")
        return False

    if not Config.UPSTOX_ACCESS_TOKEN:
        print("❌ Error: UPSTOX_ACCESS_TOKEN is missing in .env.")
        print("Please generate today's token and run again.")
        return False

    # Initialize Real Broker
    upstox = UpstoxBroker(Config)
    if not upstox.authenticate():
        print("❌ Login Failed. Token might be expired.")
        return False
        
    print("✅ Logged into Upstox Successfully.")
    
    # 1. Fetch Nifty LTP
    nifty_ltp = upstox.get_quote("NSE|Nifty 50")
    print(f"  NIFTY 50 Live: ₹{nifty_ltp}")
    if nifty_ltp <= 0:
        print("❌ Failed to fetch Nifty LTP. Ensure F&O Segment is active!")
        return False
        
    # 2. Find a Far-OTM CE Option to buy
    # Round to nearest 50, then add 2000 points to make it super cheap
    atm_strike = 50 * round(nifty_ltp / 50)
    otm_strike = atm_strike + 2000
    
    symbol_to_test = upstox.get_option_symbol("NIFTY", otm_strike, "CE")
    print(f"  Target Penny Stock: {symbol_to_test}")
    
    # Check the price of this penny option before buying
    penny_ltp = upstox.get_quote(symbol_to_test)
    print(f"  Target Price: ₹{penny_ltp}")
    
    if penny_ltp <= 0:
        print("⚠️ Failed to fetch option price. Your F&O Segment might not be activated yet.")
        print("⚠️ Exiting test to prevent blind market orders.")
        return False
        
    if penny_ltp > 10.0:
        print(f"⚠️ Safety Abort: The option is too expensive (₹{penny_ltp}).")
        print("This test is strictly for options under ₹10 to minimize risk.")
        return False
        
    qty = 25 # 1 Lot of Nifty
    max_risk = qty * penny_ltp
    
    print("\n" + "="*40)
    print(f"⚠️ YOU ARE ABOUT TO PLACE A REAL ORDER ⚠️")
    print(f"  Instrument: {symbol_to_test}")
    print(f"  Quantity:   {qty} (1 Lot)")
    print(f"  Price:      ~₹{penny_ltp}")
    print(f"  MAX RISK:   ~₹{max_risk:.2f}")
    print("="*40)
    
    confirm = input("Type 'YES' to execute this trade on your Upstox account: ")
    if confirm != "YES":
        print("Test Cancelled by User.")
        return False
        
    # 3. EXECUTE BUY
    print(f"\n🚀 Sending BUY Order for {qty} {symbol_to_test}...")
    buy_order = upstox.place_order(symbol_to_test, qty, side="BUY", order_type="MARKET")
    
    if not buy_order:
        print("❌ Buy Order Failed.")
        return False
        
    print(f"✅ BUY Order placed! Reference: {buy_order}")
    
    # 4. WAIT & VERIFY
    print("⏳ Waiting 5 seconds for order settlement...")
    time.sleep(5)
    
    # Check Positions API to see if it landed
    print("🔍 Fetching Live Positions from Upstox...")
    positions = upstox.get_positions()
    found = False
    if positions and getattr(positions, 'data', None):
        for p in positions.data:
            if getattr(p, 'tradingsymbol', '') == symbol_to_test and getattr(p, 'quantity', 0) > 0:
                print(f"  ✅ Verified! Found {p.quantity} qty in your portfolio.")
                found = True
                
    if not found:
        print("  ⚠️ Could not find position. It may have failed to execute or API is lagging.")
        
    # 5. EXECUTE SELL
    print(f"\n🚀 Sending SELL (Square-off) Order for {qty} {symbol_to_test}...")
    sell_order = upstox.place_order(symbol_to_test, qty, side="SELL", order_type="MARKET")
    
    if sell_order:
        print(f"✅ SELL Order placed! Reference: {sell_order}")
        print("\n🎉 PENNY TEST COMPLETE. System is approved for Real Money Trading!")
        return True
    else:
        print(f"❌ SELL Order Failed. YOU MUST CLOSE THIS POSITION MANUALLY IN UPSTOX APP!")
        return False


if __name__ == "__main__":
    run_penny_test()
