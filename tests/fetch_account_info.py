"""
Upstox Account Info Fetcher (READ-ONLY)
Fetches: Profile, Funds, Holdings
Does NOT place any orders or modify anything.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

import upstox_client
from config import Config

cfg = upstox_client.Configuration()
cfg.access_token = Config.UPSTOX_ACCESS_TOKEN

# ============================================================
# 1. USER PROFILE
# ============================================================
try:
    user_api = upstox_client.UserApi(upstox_client.ApiClient(cfg))
    profile = user_api.get_profile('2.0')
    d = profile.data
    print("=" * 60)
    print("ACCOUNT INFO")
    print("=" * 60)
    print(f"  Name:       {d.user_name}")
    print(f"  Email:      {d.email}")
    print(f"  User ID:    {d.user_id}")
    print(f"  Broker:     {d.broker}")
    print(f"  Exchanges:  {d.exchanges}")
    print(f"  Products:   {d.products}")
except Exception as e:
    print(f"Profile Error: {e}")

# ============================================================
# 2. FUNDS / MARGIN
# ============================================================
print()
try:
    funds = user_api.get_user_fund_margin('2.0')
    if funds and funds.data:
        print("=" * 60)
        print("FUNDS & MARGIN")
        print("=" * 60)
        
        if hasattr(funds.data, 'equity') and funds.data.equity:
            eq = funds.data.equity
            print("  [EQUITY]")
            for attr in ['available_margin', 'used_margin', 'payin_amount', 'span_margin',
                         'adhoc_margin', 'notional_cash', 'exposure_margin']:
                val = getattr(eq, attr, None)
                if val is not None:
                    label = attr.replace('_', ' ').title()
                    print(f"    {label:<22}: Rs {val:,.2f}")
        
        if hasattr(funds.data, 'commodity') and funds.data.commodity:
            co = funds.data.commodity
            print("  [COMMODITY]")
            for attr in ['available_margin', 'used_margin']:
                val = getattr(co, attr, None)
                if val is not None:
                    label = attr.replace('_', ' ').title()
                    print(f"    {label:<22}: Rs {val:,.2f}")
except Exception as e:
    print(f"Funds Error: {e}")

# ============================================================
# 3. HOLDINGS (Long-term Investments)
# ============================================================
print()
try:
    portfolio_api = upstox_client.PortfolioApi(upstox_client.ApiClient(cfg))
    holdings = portfolio_api.get_holdings('2.0')
    
    if holdings and holdings.data and len(holdings.data) > 0:
        print("=" * 60)
        print(f"HOLDINGS ({len(holdings.data)} Stocks)")
        print("=" * 60)
        
        header = f"  {'Stock':<18} {'Qty':>5} {'Avg Price':>10} {'LTP':>10} {'P&L':>12} {'Chg%':>7}"
        print(header)
        print("  " + "-" * 64)
        
        total_invested = 0
        total_current = 0
        
        for h in holdings.data:
            sym = getattr(h, 'tradingsymbol', None) or getattr(h, 'company_name', 'N/A')
            qty = getattr(h, 'quantity', 0) or 0
            avg = getattr(h, 'average_price', 0) or 0
            ltp = getattr(h, 'last_price', 0) or 0
            pnl = getattr(h, 'pnl', 0) or 0
            
            invested = avg * qty
            current = ltp * qty
            total_invested += invested
            total_current += current
            chg_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0
            
            print(f"  {str(sym)[:18]:<18} {qty:>5} {avg:>10.2f} {ltp:>10.2f} {pnl:>12.2f} {chg_pct:>6.1f}%")
        
        print("  " + "-" * 64)
        total_pnl = total_current - total_invested
        total_chg = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        print(f"  {'TOTAL':<18} {'':>5} {total_invested:>10.2f} {total_current:>10.2f} {total_pnl:>12.2f} {total_chg:>6.1f}%")
    else:
        print("HOLDINGS: None / Empty")
except Exception as e:
    print(f"Holdings Error: {e}")

# ============================================================
# 4. POSITIONS (Intraday / F&O)
# ============================================================
print()
try:
    positions = portfolio_api.get_positions('2.0')
    if positions and positions.data and len(positions.data) > 0:
        print("=" * 60)
        print(f"OPEN POSITIONS ({len(positions.data)})")
        print("=" * 60)
        for p in positions.data:
            sym = getattr(p, 'tradingsymbol', 'N/A')
            qty = getattr(p, 'quantity', 0)
            pnl = getattr(p, 'pnl', 0)
            product = getattr(p, 'product', 'N/A')
            print(f"  {sym:<25} Qty:{qty:>5}  PnL: Rs {pnl:,.2f}  ({product})")
    else:
        print("OPEN POSITIONS: None (No active trades)")
except Exception as e:
    print(f"Positions Error: {e}")

print()
print("=" * 60)
print("READ-ONLY: No orders were placed. Your account is untouched.")
print("=" * 60)
