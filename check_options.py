import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from core.brokers.upstox import UpstoxBroker

def test_options():
    print("Initializing Broker...")
    broker = UpstoxBroker(Config)
    broker.authenticate()
    
    # 1. Test NIFTY Spot
    nifty = broker.get_quote('NSE|Nifty 50')
    print(f"[SPOT] NIFTY 50 = {nifty}")
    
    if nifty <= 0:
        print("Failed to fetch NIFTY 50 spot. Exiting.")
        return
        
    # 2. Test ATM Strike
    atm = 50 * round(nifty / 50)
    print(f"[CALC] Nearest ATM Strike = {atm}")
    
    # 3. Build Option Symbol
    sym = broker.get_option_symbol("NIFTY", atm, "CE")
    print(f"[SYM] Built Option Symbol = {sym}")
    
    # 4. Fetch Option LTP
    print("Fetching quote for option...")
    opt_ltp = broker.get_quote(sym)
    print(f"[LTP] Option Price = {opt_ltp}")

if __name__ == "__main__":
    test_options()
