"""
Upstox WebSocket Client — Real-time market data via Protobuf.
Integrated with: Logger primitive.
"""
import ssl
import json
import time
import threading
import websockets
import asyncio
import requests
import core.brokers.MarketDataFeed_pb2 as pb
from core.logger import get_logger
from core.event_bus import EventBus
from core.events import TickEvent

logger = get_logger(__name__)


class UpstoxWebSocketClient:
    def __init__(self, access_token, event_bus: EventBus, on_error_callback=None):
        self.access_token = access_token
        self.event_bus = event_bus
        self.on_error_callback = on_error_callback
        self.ws = None
        self.is_connected = False
        self.subscriptions = set()
        self.price_cache = {}
        
        # Thread control
        self._stop_event = threading.Event()
        self._thread = None
        self._loop = None

    def get_authorized_url(self):
        url = "https://api.upstox.com/v2/feed/market-data-feed/authorize"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json()['data']['authorized_redirect_uri']
        else:
            logger.error(f"WS Auth Error: {res.text}")
            return None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_and_listen())

    async def _connect_and_listen(self):
        while not self._stop_event.is_set():
            try:
                ws_url = self.get_authorized_url()
                if not ws_url:
                    time.sleep(5)
                    continue
            except Exception as e:
                logger.error(f"WS Auth Exception: {e}")
                time.sleep(5)
                continue
                
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            try:
                async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                    self.ws = ws
                    self.is_connected = True
                    logger.info("✅ Upstox WebSocket Connected")
                    
                    if self.subscriptions:
                        await self._send_subscription()

                    while not self._stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=15.0)
                            self._decode_protobuf(message)
                        except asyncio.TimeoutError:
                            pass
                            
            except Exception as e:
                self.is_connected = False
                logger.warning(f"WS connection lost: {e}. Reconnecting...")
                if self.on_error_callback:
                    self.on_error_callback(e)
                await asyncio.sleep(2)
                
    def subscribe(self, symbols: list):
        new_symbols = set(symbols) - self.subscriptions
        self.subscriptions.update(symbols)
        
        if new_symbols and self.is_connected and self.ws and self._loop:
             asyncio.run_coroutine_threadsafe(self._send_subscription(), self._loop)
             
    async def _send_subscription(self):
         if not self.subscriptions: return
         payload = {
             "guid": "monie_bot",
             "method": "sub",
             "data": {
                 "mode": "full",
                 "instrumentKeys": list(self.subscriptions)
             }
         }
         await self.ws.send(json.dumps(payload).encode('utf-8'))
         
    def _decode_protobuf(self, buffer):
        try:
            feed_response = pb.FeedResponse()
            feed_response.ParseFromString(buffer)
            
            for instrument_key, feed in feed_response.feeds.items():
                ltp = 0.0
                if feed.HasField('ff') and feed.ff.HasField('market_quote'):
                    ltp = feed.ff.market_quote.ltp
                elif feed.HasField('iff') and feed.iff.HasField('ltpc'):
                    ltp = feed.iff.ltpc.ltp
                elif feed.HasField('ltpc'):
                    ltp = feed.ltpc.ltp
                
                # FullFeed / IndexFullFeed decoding fallback
                if ltp == 0.0 and feed.HasField('ff'):
                    if hasattr(feed.ff, 'market_quote') and feed.ff.market_quote.ltp > 0:
                         ltp = feed.ff.market_quote.ltp
                
                if ltp > 0:
                    self.price_cache[instrument_key] = ltp
                    
                    # Create and publish TickEvent
                    tick = TickEvent(
                        symbol=instrument_key,
                        ltp=ltp,
                        timestamp=time.time()
                    )
                    self.event_bus.publish(tick)
                        
        except Exception as e:
            # Don't spam logs on decode error
            logger.debug(f"Protobuf decode error: {e}")

    def get_cached_price(self, symbol):
        return self.price_cache.get(symbol, 0.0)
        
    def stop(self):
        self._stop_event.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
