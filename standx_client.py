"""
StandX Market Maker Client
Independent implementation using StandX SDK
"""
import os
import json
import base64
import time
import asyncio
import logging
import websockets
import requests
import base58
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple, Callable
from solders.keypair import Keypair

# Import project's internal StandX protocol modules
from standx_protocol.perps_auth import StandXAuth
from standx_protocol.perp_http import StandXPerpHTTP

from config_loader import get_config

logger = logging.getLogger(__name__)


class StandXWebSocketManager:
    """
    StandX WebSocket Manager
    Handles connection, authentication, subscription and message dispatch
    URL: wss://perps.standx.com/ws-stream/v1
    """
    def __init__(self, token: str, logger, on_message_callback: Callable):
        self.url = "wss://perps.standx.com/ws-stream/v1"
        self.token = token
        self.logger = logger
        self.on_message_callback = on_message_callback

        self._ws = None
        self._running = False
        self._task = None
        self._loop = None

    async def start(self):
        """Start WebSocket task"""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._task = self._loop.create_task(self._run_loop())

    async def stop(self):
        """Stop WebSocket"""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        """Main loop with auto-reconnect"""
        while self._running:
            try:
                self.logger.info(f"[WS] Connecting to {self.url}...")
                async with websockets.connect(self.url, ping_interval=None) as ws:
                    self._ws = ws
                    self.logger.info("[WS] Connected")

                    # Authenticate and subscribe
                    await self._authenticate_and_subscribe()

                    # Message listening loop
                    while self._running:
                        try:
                            msg = await ws.recv()
                            self._handle_message(msg)
                        except websockets.ConnectionClosed:
                            self.logger.warning("[WS] Connection closed by server")
                            break
                        except Exception as e:
                            self.logger.error(f"[WS] Receive error: {e}")
                            break

            except Exception as e:
                self.logger.error(f"[WS] Connection error: {e}")

            if self._running:
                self.logger.info("[WS] Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def _authenticate_and_subscribe(self):
        """Send authentication and subscribe to order updates"""
        # Auth message
        auth_msg = {
            "method": "auth",
            "params": {"token": self.token}
        }
        await self._ws.send(json.dumps(auth_msg))
        self.logger.info("[WS] Sent authentication")

        # Subscribe to order updates
        subscribe_msg = {
            "method": "subscribe",
            "params": ["order"]
        }
        await self._ws.send(json.dumps(subscribe_msg))
        self.logger.info("[WS] Subscribed to order updates")

    def _handle_message(self, msg_str: str):
        """Handle WebSocket message"""
        try:
            msg = json.loads(msg_str)

            # Handle different message types
            if msg.get("type") == "order":
                # Order update
                order_data = msg.get("data", {})
                self.on_message_callback(order_data)
            elif msg.get("type") == "pong":
                # Pong response (heartbeat)
                pass
            else:
                # Other messages
                self.logger.debug(f"[WS] Received: {msg}")

        except Exception as e:
            self.logger.error(f"[WS] Error handling message: {e}")


class OrderInfo:
    """Order tracking information"""
    def __init__(self, order_id: str, side: str, price: float, qty: float,
                 status: str = "pending", cl_ord_id: str = None):
        self.order_id = order_id
        self.side = side
        self.price = price
        self.qty = qty
        self.status = status
        self.cl_ord_id = cl_ord_id
        self.timestamp = time.time()


class StandXMarketMaker:
    """StandX Market Making Bot - Based on cross-exchange-arbitrage implementation"""

    def __init__(self, config):
        """
        Initialize market maker.

        Args:
            config: Config instance
        """
        self.config = config
        self.symbol = config.get("trading.symbol", "BTC-USD")
        self.spread_pct = config.get("trading.spread_percentage", 0.1) / 100.0
        self.order_size = config.get("trading.order_size", "0.01")
        self.leverage = config.get("trading.leverage", 1)
        self.margin_mode = config.get("trading.margin_mode", "cross")
        self.check_interval = config.get("trading.check_interval_seconds", 5)
        self.cancel_threshold = config.get("strategy.cancel_distance_percentage", 0.05) / 100.0

        # API URLs - check environment variables first, then config, then defaults
        self.base_url = os.getenv('STANDX_BASE_URL') or config.get("exchanges.standx.trade_url", "https://perps.standx.com")
        self.auth_url = os.getenv('STANDX_AUTH_URL') or config.get("exchanges.standx.auth_url", "https://api.standx.com")

        # Initialize StandX clients
        self.http_client = StandXPerpHTTP(base_url=self.base_url)

        # Load Solana wallet FIRST
        private_key_str = config.get_solana_private_key()
        clean_key = private_key_str.replace("0x", "").strip()
        private_key_bytes = base58.b58decode(clean_key)
        self.keypair = Keypair.from_bytes(private_key_bytes)
        self.wallet_address = str(self.keypair.pubkey())

        # Initialize auth client with Solana private key seed (first 32 bytes)
        # Solana keypair format: 64 bytes = 32-byte seed + 32-byte pubkey
        solana_seed = private_key_bytes[:32]
        self.auth_client = StandXAuth(private_key=solana_seed)

        # Authentication token
        self.token = None

        # WebSocket manager
        self.ws_manager = None
        self._order_update_handler = None

        # Track active orders
        self.active_orders: Dict[str, OrderInfo] = {}

        # Current market price
        self.current_price = None

        logger.info(f"Initialized StandX Market Maker for {self.symbol}")
        logger.info(f"Wallet: {self.wallet_address[:10]}...")

    def construct_solana_signature(self, jwt_payload: Dict, raw_sig: bytes, msg_bytes: bytes) -> str:
        """Construct Solana signature for StandX authentication"""
        input_data = {
            "domain": jwt_payload.get("domain"),
            "address": jwt_payload.get("address"),
            "statement": jwt_payload.get("statement"),
            "uri": jwt_payload.get("uri"),
            "version": jwt_payload.get("version"),
            "chainId": jwt_payload.get("chainId"),
            "nonce": jwt_payload.get("nonce"),
            "issuedAt": jwt_payload.get("issuedAt"),
            "requestId": jwt_payload.get("requestId")
        }
        output_data = {
            "account": {"publicKey": list(bytes(self.keypair.pubkey()))},
            "signature": list(raw_sig),
            "signedMessage": list(msg_bytes)
        }
        complex_obj = {"input": input_data, "output": output_data}
        json_str = json.dumps(complex_obj, separators=(',', ':'))
        return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

    async def connect(self) -> bool:
        """
        Connect to StandX: REST login -> Start WebSocket

        Returns:
            True if successful
        """
        try:
            logger.info("Connecting to StandX...")

            # 1. Sync login to get token
            await asyncio.to_thread(self._perform_login)

            # 2. Start WebSocket for order updates
            await self._start_websocket()

            logger.info("Connected to StandX successfully")
            return True

        except Exception as e:
            logger.error(f"StandX connection failed: {e}")
            return False

    def _perform_login(self):
        """Synchronous login logic"""
        # 1. Prepare signin
        req_id = str(self.keypair.pubkey())
        resp = requests.post(
            f"{self.auth_url}/v1/offchain/prepare-signin?chain=solana",
            json={"address": self.wallet_address, "requestId": req_id},
            timeout=10
        )
        if not resp.ok:
            raise ValueError(f"Prepare failed: {resp.text}")

        data = resp.json()
        if not data.get("success"):
            raise ValueError(f"API Error: {data.get('message')}")

        signed_data_jwt = data["signedData"]

        # 2. Parse JWT & Sign
        parts = signed_data_jwt.split('.')
        padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
        jwt_payload = json.loads(base64.b64decode(padded).decode('utf-8'))

        msg_bytes = jwt_payload.get("message").encode('utf-8')
        raw_sig = bytes(self.keypair.sign_message(msg_bytes))

        # 3. Construct signature
        final_sig = self.construct_solana_signature(jwt_payload, raw_sig, msg_bytes)

        # 4. Login
        resp = requests.post(
            f"{self.auth_url}/v1/offchain/login?chain=solana",
            json={
                "signature": final_sig,
                "signedData": signed_data_jwt,
                "expiresSeconds": 604800
            },
            timeout=10
        )
        if not resp.ok:
            raise ValueError(f"Login failed: {resp.text}")

        result = resp.json()
        self.token = result.get("token")
        if not self.token:
            raise ValueError(f"Login failed: no token in response")

        logger.info(f"StandX Login Success (Address: {result.get('address', 'N/A')})")

    async def _start_websocket(self):
        """Start WebSocket connection"""
        if self.token:
            self.ws_manager = StandXWebSocketManager(
                token=self.token,
                logger=logger,
                on_message_callback=self._on_ws_order_update
            )
            await self.ws_manager.start()

    def _on_ws_order_update(self, order_data: dict):
        """WebSocket order update callback"""
        try:
            order_id = order_data.get("id") or order_data.get("order_id")
            if not order_id:
                return

            status = order_data.get("status", "").lower()
            side = order_data.get("side", "")
            price = float(order_data.get("price", 0))
            qty = float(order_data.get("qty", 0) or order_data.get("size", 0))
            filled_qty = float(order_data.get("filled_qty", 0) or order_data.get("filled_size", 0))

            # Update order info
            if order_id in self.active_orders:
                order_info = self.active_orders[order_id]
                order_info.status = status

                # If filled, trigger callback
                if status in ["filled", "completed"] and filled_qty > 0:
                    fill_value = filled_qty * price
                    logger.info(f"✓ FILLED: {side.upper()} {filled_qty} {self.symbol} @ ${price:,.2f} (${fill_value:,.2f})")
                    if self._order_update_handler:
                        self._order_update_handler({
                            "order_id": order_id,
                            "side": side,
                            "price": price,
                            "qty": filled_qty,
                            "status": "filled"
                        })
                    # Remove from active orders
                    del self.active_orders[order_id]
                elif status in ["cancelled", "canceled", "rejected"]:
                    # Remove from active orders
                    if order_id in self.active_orders:
                        del self.active_orders[order_id]

        except Exception as e:
            logger.error(f"Error processing order update: {e}")

    def setup_order_update_handler(self, handler: Callable):
        """Setup callback for order fills"""
        self._order_update_handler = handler

    def get_ticker(self, symbol: str = None) -> dict:
        """Get current ticker data (BBO)"""
        try:
            symbol = symbol or self.symbol
            url = f"{self.base_url}/api/query_symbol_price"
            params = {"symbol": symbol}
            resp = requests.get(url, params=params, timeout=5)

            if not resp.ok:
                logger.error(f"Failed to get ticker: {resp.status_code}")
                return {"bid_price": 0, "ask_price": 0}

            data = resp.json()
            return {
                "bid_price": data.get("spread_bid", 0) or 0,
                "ask_price": data.get("spread_ask", 0) or 0,
                "mark_price": data.get("mark_price", 0) or 0
            }
        except Exception as e:
            logger.error(f"Error getting ticker: {e}")
            return {"bid_price": 0, "ask_price": 0}

    async def place_order(self, side: str, price: float, qty: float = None) -> Optional[OrderInfo]:
        """
        Place a limit order

        Args:
            side: "buy" or "sell"
            price: Order price
            qty: Order quantity (uses config if None)

        Returns:
            OrderInfo if successful, None otherwise
        """
        try:
            qty = qty or float(self.order_size)
            cl_ord_id = f"{side}_{int(time.time() * 1000)}"

            # Use http_client.place_order() with auth for request signing
            response = self.http_client.place_order(
                token=self.token,
                symbol=self.symbol,
                side=side,
                order_type="limit",
                qty=str(qty),
                price=str(price),
                time_in_force="gtc",
                reduce_only=False,
                cl_ord_id=cl_ord_id,
                auth=self.auth_client  # Now using correctly initialized auth with Solana seed
            )

            # Log order placement with trading details
            logger.info(f"Order placed: {side.upper()} {qty} {self.symbol} @ ${price}")

            # Extract order ID from response
            order_id = str(response.get("request_id", cl_ord_id))

            order_info = OrderInfo(
                order_id=order_id,
                side=side,
                price=price,
                qty=qty,
                cl_ord_id=cl_ord_id
            )

            self.active_orders[order_id] = order_info
            return order_info

        except Exception as e:
            logger.error(f"Failed to place {side} order: {e}")
            return None

    async def cancel_orders(self, order_ids: List[str] = None) -> bool:
        """
        Cancel orders by ID list

        Args:
            order_ids: List of order IDs (if None, cancels all)

        Returns:
            True if successful
        """
        try:
            if order_ids is None:
                order_ids = list(self.active_orders.keys())

            if not order_ids:
                return True

            # Convert to integers if needed
            order_id_list = []
            for oid in order_ids:
                try:
                    order_id_list.append(int(oid))
                except ValueError:
                    # If conversion fails, might be cl_ord_id
                    pass

            if order_id_list:
                self.http_client.cancel_orders(
                    token=self.token,
                    order_id_list=order_id_list,
                    auth=self.auth_client
                )
                logger.info(f"Cancelled {len(order_id_list)} orders")

            # Remove from tracking
            for oid in order_ids:
                if oid in self.active_orders:
                    del self.active_orders[oid]

            return True

        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
            return False

    async def sync_open_orders(self):
        """Sync active orders with exchange"""
        try:
            open_orders_data = self.http_client.query_open_orders(
                token=self.token,
                symbol=self.symbol
            )

            result = open_orders_data.get("result", [])

            # Update our tracking
            new_active_orders = {}
            for order_data in result:
                order_id = str(order_data.get("id") or order_data.get("order_id"))
                if order_id:
                    order_info = OrderInfo(
                        order_id=order_id,
                        side=order_data.get("side"),
                        price=float(order_data.get("price", 0)),
                        qty=float(order_data.get("qty", 0) or order_data.get("size", 0)),
                        status=order_data.get("status", "open"),
                        cl_ord_id=order_data.get("cl_ord_id")
                    )
                    new_active_orders[order_id] = order_info

            self.active_orders = new_active_orders
            logger.debug(f"Synced {len(self.active_orders)} open orders")

        except Exception as e:
            logger.error(f"Failed to sync orders: {e}")

    async def get_position(self) -> Decimal:
        """Get current position quantity"""
        try:
            positions = self.http_client.query_positions(
                token=self.token,
                symbol=self.symbol
            )

            for pos in positions:
                if pos.get("symbol") == self.symbol and pos.get("status") == "open":
                    qty = pos.get("qty", 0)
                    return Decimal(str(qty)) if qty else Decimal('0')

            return Decimal('0')

        except Exception as e:
            logger.error(f"Failed to get position: {e}")
            return Decimal('0')

    async def disconnect(self):
        """Disconnect from StandX"""
        if self.ws_manager:
            await self.ws_manager.stop()
        logger.info("Disconnected from StandX")
