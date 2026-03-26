"""
Upstox WebSocket Client — Real-time market data via official SDK Feeder.
Uses Upstox's built-in protobuf decoder (no manual .pb2 compilation required).
Integrated with: Logger primitive, EventBus.
"""
import time
import threading
from core.logger import get_logger
from core.event_bus import EventBus
from core.events import TickEvent

logger = get_logger(__name__)


class UpstoxWebSocketClient:
    def __init__(self, access_token, event_bus: EventBus, on_error_callback=None):
        self.access_token = access_token
        self.event_bus = event_bus
        self.on_error_callback = on_error_callback
        self.is_connected = False
        self.subscriptions = set()
        self.price_cache = {}
        self.streamer = None
        
        # Thread control
        self._stop_event = threading.Event()

    def start(self):
        """Starts the WebSocket using Upstox SDK's built-in MarketDataStreamer."""
        if self.is_connected:
            return
        try:
            import upstox_client
            from upstox_client.feeder import MarketDataStreamerV3

            configuration = upstox_client.Configuration()
            configuration.access_token = self.access_token
            
            self.streamer = MarketDataStreamerV3(
                upstox_client.ApiClient(configuration),
                instrumentKeys=list(self.subscriptions) if self.subscriptions else [],
                mode="full"
            )
            
            # Register event handlers
            self.streamer.on("message", self._on_message)
            self.streamer.on("open", self._on_open)
            self.streamer.on("error", self._on_error)
            self.streamer.on("close", self._on_close)
            
            # Connect (runs in its own thread internally)
            self.streamer.connect()
            
        except ImportError:
            logger.warning("MarketDataStreamerV3 not found in SDK. Trying legacy websocket...")
            self._start_legacy()
        except Exception as e:
            logger.error(f"Could not start WebSocket: {e}. Falling back to REST polling.")
            if self.on_error_callback:
                self.on_error_callback(e)

    def _start_legacy(self):
        """Fallback: manual websocket connection using raw protobuf (legacy approach)."""
        try:
            import core.brokers.MarketDataFeed_pb2 as pb
            self._pb = pb
            self._thread = threading.Thread(target=self._run_legacy_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            logger.error(f"Legacy WebSocket also failed: {e}. Falling back to REST polling.")

    def _run_legacy_loop(self):
        """Legacy WebSocket loop using raw protobuf."""
        import asyncio
        import ssl
        import json
        import websockets
        import requests
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while not self._stop_event.is_set():
            try:
                url = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
                headers = {
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {self.access_token}'
                }
                res = requests.get(url, headers=headers)
                if res.status_code != 200:
                    logger.error(f"WS Auth Error: HTTP {res.status_code}")
                    time.sleep(5)
                    continue
                ws_url = res.json()['data']['authorized_redirect_uri']
            except Exception as e:
                logger.error(f"WS Auth Exception: {e}")
                time.sleep(5)
                continue
            
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            async def _connect():
                try:
                    async with websockets.connect(ws_url, ssl=ssl_context) as ws:
                        self.is_connected = True
                        logger.info("✅ Upstox WebSocket Connected (Legacy)")
                        
                        if self.subscriptions:
                            payload = {
                                "guid": "monie_bot",
                                "method": "sub",
                                "data": {
                                    "mode": "full",
                                    "instrumentKeys": list(self.subscriptions)
                                }
                            }
                            await ws.send(json.dumps(payload).encode('utf-8'))
                        
                        while not self._stop_event.is_set():
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=15.0)
                                self._decode_legacy_protobuf(message)
                            except asyncio.TimeoutError:
                                pass
                except Exception as e:
                    self.is_connected = False
                    logger.warning(f"WS connection lost: {e}. Reconnecting...")
            
            loop.run_until_complete(_connect())
            if not self._stop_event.is_set():
                time.sleep(2)

    def _decode_legacy_protobuf(self, buffer):
        """Decode protobuf messages using the legacy .pb2 file."""
        try:
            feed_response = self._pb.FeedResponse()
            feed_response.ParseFromString(buffer)
            
            for instrument_key, feed in feed_response.feeds.items():
                ltp = 0.0
                if feed.HasField('ff') and feed.ff.HasField('market_quote'):
                    ltp = feed.ff.market_quote.ltp
                elif feed.HasField('iff') and feed.iff.HasField('ltpc'):
                    ltp = feed.iff.ltpc.ltp
                elif feed.HasField('ltpc'):
                    ltp = feed.ltpc.ltp
                
                if ltp == 0.0 and feed.HasField('ff'):
                    if hasattr(feed.ff, 'market_quote') and feed.ff.market_quote.ltp > 0:
                        ltp = feed.ff.market_quote.ltp
                
                if ltp > 0:
                    self.price_cache[instrument_key] = ltp
                    tick = TickEvent(symbol=instrument_key, ltp=ltp, timestamp=time.time())
                    self.event_bus.publish(tick)
        except Exception as e:
            logger.debug(f"Protobuf decode error: {e}")

    def _on_open(self):
        """Called when the V3 SDK WebSocket connects."""
        self.is_connected = True
        logger.info("✅ Upstox WebSocket Connected (V3 SDK Streamer)")

    def _on_message(self, message):
        """Called when V3 SDK WebSocket receives data. Message is already decoded by the SDK."""
        try:
            # The SDK's MarketDataStreamerV3 returns decoded Python dict/object
            if hasattr(message, 'feeds'):
                feeds = message.feeds
            elif isinstance(message, dict):
                feeds = message.get('feeds', {})
            else:
                return
                
            for instrument_key, feed_data in feeds.items():
                ltp = 0.0
                try:
                    if hasattr(feed_data, 'ff'):
                        if hasattr(feed_data.ff, 'market_quote') and feed_data.ff.market_quote:
                            ltp = feed_data.ff.market_quote.ltp
                    elif hasattr(feed_data, 'iff'):
                        if hasattr(feed_data.iff, 'ltpc') and feed_data.iff.ltpc:
                            ltp = feed_data.iff.ltpc.ltp
                    elif isinstance(feed_data, dict):
                        ff = feed_data.get('ff', {})
                        if ff:
                            mq = ff.get('marketOHLC', ff.get('market_quote', ff.get('ltpc', {})))
                            if isinstance(mq, dict):
                                ltp = mq.get('ltp', 0.0)
                            elif hasattr(mq, 'ltp'):
                                ltp = mq.ltp
                except Exception:
                    pass
                    
                if ltp > 0:
                    self.price_cache[instrument_key] = ltp
                    tick = TickEvent(symbol=instrument_key, ltp=ltp, timestamp=time.time())
                    self.event_bus.publish(tick)
        except Exception as e:
            logger.debug(f"V3 message decode error: {e}")

    def _on_error(self, error):
        """Called when V3 SDK WebSocket encounters an error."""
        logger.error(f"WS V3 Error: {error}")
        self.is_connected = False
        if self.on_error_callback:
            self.on_error_callback(error)

    def _on_close(self):
        """Called when V3 SDK WebSocket closes."""
        self.is_connected = False
        logger.warning("WS V3 connection closed. Will auto-reconnect.")

    def subscribe(self, symbols: list):
        """Subscribe to additional instrument keys."""
        new_symbols = set(symbols) - self.subscriptions
        self.subscriptions.update(symbols)
        
        if new_symbols and self.streamer:
            try:
                self.streamer.subscribe(list(new_symbols), "full")
            except Exception as e:
                logger.warning(f"V3 subscribe error: {e}")

    def get_cached_price(self, symbol):
        return self.price_cache.get(symbol, 0.0)

    def stop(self):
        self._stop_event.set()
        if self.streamer:
            try:
                self.streamer.disconnect()
            except Exception:
                pass
        logger.info("WebSocket client stopped.")
