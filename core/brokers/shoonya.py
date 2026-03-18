"""
Shoonya Broker Adapter (NorenApi)
Zero Brokerage Trading Interface
"""
import pyotp
from core.brokers.base_broker import BaseBroker
from NorenRestApiPy.NorenApi import NorenApi

class ShoonyaBroker(BaseBroker):
    def __init__(self, config):
        self.api = NorenApi(
            host='https://api.shoonya.com/NorenWClientTP/',
            websocket='wss://api.shoonya.com/NorenWSTP/'
        )
        self.config = config
        self.is_logged_in = False

    def authenticate(self):
        """Logs in using TOTP."""
        try:
            # Generate TOTP
            try:
                totp = pyotp.TOTP(self.config.SHOONYA_TOTP_SECRET).now()
            except Exception:
                print("Error: Invalid TOTP Secret in config")
                return False

            ret = self.api.login(
                userid=self.config.SHOONYA_USER_ID,
                password=self.config.SHOONYA_PASSWORD,
                twoFA=totp,
                vendor_code=self.config.SHOONYA_VENDOR_CODE,
                api_secret=self.config.SHOONYA_API_KEY,
                imei=self.config.SHOONYA_IMEI
            )
            
            if ret and ret.get('stat') == 'Ok':
                self.is_logged_in = True
                print("Shoonya Login Successful!")
                return True
            else:
                print(f"Login Failed: {ret.get('emsg')}")
                return False
                
        except Exception as e:
            print(f"Login Error: {e}")
            return False

    def get_quote(self, symbol: str, exchange: str = "NSE"):
        """Fetches LTP for a symbol."""
        # Note: Shoonya requires token searching first, simplified here
        # Assuming symbol is formatted as "Exchange|Token" or handled via search
        pass

    def place_order(self, symbol: str, quantity: int, side: str, order_type: str = "MKT", price: float = 0.0, exchange="NSE"):
        """Places an order."""
        if not self.is_logged_in:
            return {"status": "error", "msg": "Not Logged In"}
            
        buy_or_sell = 'B' if side.upper() == 'BUY' else 'S'
        
        ret = self.api.place_order(
            buy_or_sell=buy_or_sell,
            product_type='I',  # Intraday
            exchange=exchange,
            tradingsymbol=symbol,
            quantity=quantity,
            discloseqty=0,
            price_type=order_type,
            price=0,
            trigger_price=0,
            retention='DAY',
            remarks='MonieBot'
        )
        return ret

    def get_positions(self):
        """Returns open positions."""
        if not self.is_logged_in:
            return []
        return self.api.get_positions()

    def get_pnl(self):
        """Calculates total PnL."""
        positions = self.get_positions()
        if not positions:
            return 0.0
            
        total_pnl = 0.0
        for pos in positions:
            if pos['stat'] == 'Ok':
                # Realized + Unrealized PnL logic needed here based on Shoonya response structure
                mrk_pnl = float(pos.get('urpnl', 0)) + float(pos.get('rpnl', 0))
                total_pnl += mrk_pnl
        return total_pnl
