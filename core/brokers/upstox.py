
import upstox_client
from upstox_client.rest import ApiException
from core.brokers.base_broker import BaseBroker
from core.logger import get_logger
from core.data_sanitizer import DataSanitizer
import pandas as pd
import datetime

logger = get_logger(__name__)


class UpstoxBroker(BaseBroker):
    def __init__(self, config, event_bus=None):
        self.config = config
        self.event_bus = event_bus
        self.api_instance = None
        self.quote_instance = None
        self.portfolio_api = None
        self.access_token = None
        self.is_logged_in = False
        self.ws_client = None
        self.sanitizer = DataSanitizer(event_bus=self.event_bus)  # Primitive 2: Clean all quotes
        
    def authenticate(self):
        try:
            if hasattr(self.config, 'UPSTOX_ACCESS_TOKEN') and self.config.UPSTOX_ACCESS_TOKEN:
                configuration = upstox_client.Configuration()
                configuration.access_token = self.config.UPSTOX_ACCESS_TOKEN
                api_client = upstox_client.ApiClient(configuration)
                
                # Reuse a SINGLE ApiClient for all API instances (performance)
                self.api_instance = upstox_client.OrderApi(api_client)
                self.quote_instance = upstox_client.MarketQuoteApi(api_client)
                self.portfolio_api = upstox_client.PortfolioApi(api_client)
                self.is_logged_in = True
                logger.info("✅ Upstox Client Initialized (Using Provided Access Token)")
                
                # Also hot-reload the WebSocket token if the background thread is running
                if hasattr(self, 'ws_client') and self.ws_client:
                    self.ws_client.access_token = self.config.UPSTOX_ACCESS_TOKEN
                    
                return True
            else:
                logger.error("Upstox requires 'UPSTOX_ACCESS_TOKEN' in .env")
                return False
                
        except Exception as e:
            logger.error(f"Upstox Auth Error: {e}")
            return False

    def start_websocket(self, on_error_callback=None):
        if not getattr(self.config, 'USE_WEBSOCKET', False):
            return
            
        try:
            from core.brokers.upstox_websocket import UpstoxWebSocketClient
            self.ws_client = UpstoxWebSocketClient(
                access_token=self.config.UPSTOX_ACCESS_TOKEN,
                event_bus=self.event_bus,
                on_error_callback=on_error_callback
            )
            self.ws_client.start()
        except ImportError as e:
            logger.warning(f"Could not start WebSocket client: {e}. Falling back to REST polling.")
            self.ws_client = None

    def subscribe(self, symbols: list):
        if self.ws_client:
            instrument_tokens = []
            for sym in symbols:
                token = self._get_instrument_token(sym)
                if token:
                    instrument_tokens.append(token)
            self.ws_client.subscribe(instrument_tokens)

    def place_order(self, symbol, quantity, side, order_type="MARKET", price=0.0):
        if not self.is_logged_in: return None
        
        instrument_token = self._get_instrument_token(symbol)
        if not instrument_token:
            logger.error(f"Symbol not found: {symbol}")
            return None
        
        txn_type = "BUY" if side == "BUY" else "SELL"
        
        # Primitive 4: Idempotent order tag
        order_tag = self.generate_order_tag("UPSTOX", symbol, side)
        
        body = upstox_client.PlaceOrderRequest(
            quantity=int(quantity),
            product='I',
            validity='DAY',
            price=float(price) if order_type == "LIMIT" else 0.0,
            tag=order_tag,
            instrument_token=instrument_token,
            order_type='MARKET' if order_type == "MARKET" else 'LIMIT',
            transaction_type=txn_type,
            disclosed_quantity=0,
            trigger_price=0.0,
            is_amo=False
        )
        
        # Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
        import time as _time
        for attempt in range(3):
            try:
                api_response = self.api_instance.place_order(body, "2.0")
                logger.info(f"✅ Order Placed [{order_tag}]: {side} {quantity}x {symbol} → {api_response.data.order_id}")
                return api_response.data.order_id
                
            except ApiException as e:
                if '429' in str(e) or 'rate' in str(e).lower():
                    logger.warning(f"Rate Limit Hit. Pausing 30s... [{order_tag}]")
                    _time.sleep(30)
                elif attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"Order attempt {attempt+1} failed: {e}. Retrying in {wait}s... [{order_tag}]")
                    _time.sleep(wait)
                else:
                    logger.error(f"Order Failed after 3 attempts [{order_tag}]: {e}")
                    return None
            except Exception as e:
                if attempt < 2:
                    _time.sleep(2 ** attempt)
                else:
                    logger.error(f"Order Error [{order_tag}]: {e}")
                    return None
        return None

    def get_quote(self, symbol):
        """Fetches LTP with DataSanitizer cleaning (Primitive 2)."""
        if not self.is_logged_in: return 0.0
        try:
            instrument_token = self._get_instrument_token(symbol)
            
            # --- WebSocket Fast Path ---
            if getattr(self.config, 'USE_WEBSOCKET', False) and self.ws_client:
                cached_price = self.ws_client.get_cached_price(instrument_token)
                if cached_price > 0:
                    return self.sanitizer.clean(symbol, cached_price)
                    
            # --- REST Polling Fallback (reuse existing quote_instance) ---
            api_response = self.quote_instance.ltp(instrument_token, "2.0")
            
            if api_response and api_response.data:
                for key, val in api_response.data.items():
                    if hasattr(val, 'last_price') and val.last_price is not None:
                        raw_price = float(val.last_price)
                        return self.sanitizer.clean(symbol, raw_price)
            return 0.0
        except Exception as e:
            return 0.0
            
    def get_pnl(self):
        """Returns total PnL from Upstox positions (reuses single ApiClient)."""
        if not self.is_logged_in: return 0.0
        try:
            response = self.portfolio_api.get_positions("2.0")
            if response and response.data:
                total_pnl = 0.0
                for pos in response.data:
                    mtm = getattr(pos, 'm2m', 0.0)
                    real = getattr(pos, 'realised', 0.0)
                    unreal = getattr(pos, 'unrealised', 0.0)
                    
                    if mtm: total_pnl += mtm
                    else: total_pnl += (real + unreal)
                    
                return total_pnl
            return 0.0
        except Exception as e:
            logger.debug(f"PnL fetch error: {e}")
            return 0.0

    def get_available_margin(self) -> float:
        """Fetches actual available margin from Upstox wallet.
        
        Upstox SDK returns response.data as a dict, with 'equity' value
        being a string repr of a Python dict. We parse it to get available_margin.
        """
        if not self.is_logged_in:
            return 0.0
        try:
            import ast
            user_api = upstox_client.UserApi(self.api_instance.api_client)
            response = user_api.get_user_fund_margin("2.0")
            if response and response.data:
                data = response.data
                # response.data is a dict with 'equity' and 'commodity' keys
                equity_raw = data.get('equity') if isinstance(data, dict) else getattr(data, 'equity', None)
                
                if equity_raw:
                    # Equity value may be a string repr of a dict e.g. "{'available_margin': 88070.0, ...}"
                    if isinstance(equity_raw, str):
                        equity = ast.literal_eval(equity_raw)
                    elif isinstance(equity_raw, dict):
                        equity = equity_raw
                    else:
                        # SDK model object
                        equity = {'available_margin': getattr(equity_raw, 'available_margin', 0.0),
                                  'used_margin': getattr(equity_raw, 'used_margin', 0.0)}
                    
                    available = float(equity.get('available_margin', 0.0))
                    used = float(equity.get('used_margin', 0.0))
                    logger.info(f"Upstox Wallet: Available Rs.{available:.2f}, Used Rs.{used:.2f}")
                    return available
            return 0.0
        except Exception as e:
            logger.warning(f"Could not fetch margin (non-fatal): {e}")
            return 0.0

    def get_positions(self):
        pass

    def _get_instrument_token(self, symbol):
        symbol_map = {
            "NSE|Nifty 50": "NSE_INDEX|Nifty 50",
            "NSE|INDIA VIX": "NSE_INDEX|India VIX",
            "NSE|Nifty Bank": "NSE_INDEX|Nifty Bank",
        }
        if symbol in symbol_map:
            return symbol_map[symbol]
        if "NSE_INDEX|" in symbol or "NSE_FO|" in symbol or "NSE_EQ|" in symbol:
            return symbol
        return symbol

    def _load_contracts(self):
        if hasattr(self, 'contracts_data') and self.contracts_data is not None:
            return
        try:
            logger.info("⏳ Downloading Upstox Master Contracts (complete.json.gz)...")
            import urllib.request
            import gzip
            import json
            req = urllib.request.Request('https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                gzip_file = gzip.GzipFile(fileobj=response)
                self.contracts_data = json.loads(gzip_file.read())
            logger.info("✅ Contracts loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to download Upstox contracts: {e}")
            self.contracts_data = None

    def get_option_symbol(self, underlying="NIFTY", strike=22000, side="CE", expiry_offset=0):
        self._load_contracts()
        if not getattr(self, 'contracts_data', None):
            logger.error("Contract Master not available.")
            return None
            
        try:
            matches = []
            for d in self.contracts_data:
                if d.get('instrument_type') == side and d.get('name') == underlying:
                    s = d.get('strike_price')
                    if s is not None and float(s) == float(strike):
                        matches.append(d)
                        
            if not matches:
                logger.warning(f"No option for {underlying} strike={strike} side={side}")
                return None
                
            def get_expiry(contract):
                return pd.to_datetime(contract.get('expiry'), unit='ms').date()
                
            unique_expiries = sorted(list(set([get_expiry(m) for m in matches])))
            
            if expiry_offset >= len(unique_expiries):
                logger.warning(f"Expiry offset {expiry_offset} out of bounds.")
                return None
                
            target_expiry = unique_expiries[expiry_offset]
            
            for m in matches:
                if get_expiry(m) == target_expiry:
                    return m.get('instrument_key')
                    
            return None
            
        except Exception as e:
            logger.error(f"Upstox Symbol Mapping Error: {e}")
            return None
