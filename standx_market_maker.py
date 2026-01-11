"""
StandX Market Making Strategy
Continuously places bid/ask orders within 10% spread and cancels when price moves
Based on cross-exchange-arbitrage project implementation
"""
import sys
import os
import time
import base58
import base64
import json
import asyncio
import logging
import requests
from typing import Dict, List, Optional, Tuple, Callable
from decimal import Decimal
from solders.keypair import Keypair
import websockets

# Add parent directory to path to import standx modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

try:
    from DD_strategy_bot.exchange.exchange_standx.standx_protocol.perp_http import StandXPerpHTTP
    from DD_strategy_bot.exchange.exchange_standx.standx_protocol.perps_auth import StandXAuth
except ImportError:
    # Fallback to cross-exchange-arbitrage location
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'cross-exchange-arbitrage'))
    from exchanges.standx_protocol.perp_http import StandXPerpHTTP
    from exchanges.standx_protocol.perps_auth import StandXAuth

from config_loader import get_config


logger = logging.getLogger(__name__)


class OrderInfo:
    """Order tracking information"""
    def __init__(self, order_id: int, side: str, price: float, qty: float, cl_ord_id: str = None):
        self.order_id = order_id
        self.side = side
        self.price = price
        self.qty = qty
        self.cl_ord_id = cl_ord_id
        self.timestamp = time.time()


class StandXMarketMaker:
    """StandX Market Making Bot"""

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

        # Initialize StandX clients
        self.http_client = StandXPerpHTTP(
            base_url=config.get("exchanges.standx.trade_url"),
            geo_url=config.get("exchanges.standx.geo_url")
        )

        # Initialize authentication
        private_key_str = config.get_solana_private_key()
        clean_key = private_key_str.replace("0x", "").strip()
        private_key_bytes = base58.b58decode(clean_key)

        # Store keypair for signing
        self.keypair = Keypair.from_bytes(private_key_bytes)
        self.wallet_address = str(self.keypair.pubkey())

        # Create StandXAuth for request signing (uses internal ed25519 key)
        self.auth = StandXAuth()

        # Authentication token
        self.token = None

        # Track active orders
        self.active_orders: Dict[int, OrderInfo] = {}

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

    def login(self) -> bool:
        """
        Login to StandX and get authentication token.

        Returns:
            True if successful, False otherwise
        """
        try:
            import requests

            auth_url = self.config.get("exchanges.standx.auth_url")
            chain = self.config.get("exchanges.standx.chain", "solana")

            logger.info(f"Logging in to StandX with wallet {self.wallet_address[:10]}...")

            # 1. Prepare signin
            resp = requests.post(
                f"{auth_url}/v1/offchain/prepare-signin?chain={chain}",
                json={"address": self.wallet_address, "requestId": str(self.keypair.pubkey())}
            )
            if not resp.ok:
                raise Exception(f"Prepare failed: {resp.text}")

            signed_data_jwt = resp.json()["signedData"]

            # 2. Sign message
            parts = signed_data_jwt.split('.')
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            jwt_payload = json.loads(base64.b64decode(padded).decode('utf-8'))
            msg_bytes = jwt_payload.get("message").encode('utf-8')
            raw_sig = bytes(self.keypair.sign_message(msg_bytes))

            # 3. Construct signature
            final_sig = self.construct_solana_signature(jwt_payload, raw_sig, msg_bytes)

            # 4. Login
            resp = requests.post(
                f"{auth_url}/v1/offchain/login?chain={chain}",
                json={
                    "signature": final_sig,
                    "signedData": signed_data_jwt,
                    "expiresSeconds": 604800
                }
            )
            if not resp.ok:
                raise Exception(f"Login failed: {resp.text}")

            self.token = resp.json().get("token")
            logger.info("Successfully logged in to StandX")
            return True

        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def get_current_price(self) -> Optional[float]:
        """
        Get current market price for the symbol.

        Returns:
            Current price or None if failed
        """
        try:
            price_data = self.http_client.query_symbol_price(self.symbol)
            mark_price = price_data.get("mark_price")
            if mark_price:
                self.current_price = float(mark_price)
                return self.current_price
            return None
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return None

    def calculate_order_prices(self, current_price: float) -> Tuple[float, float]:
        """
        Calculate bid and ask prices based on spread.

        Args:
            current_price: Current market price

        Returns:
            (bid_price, ask_price) tuple
        """
        spread_amount = current_price * self.spread_pct
        bid_price = current_price - spread_amount
        ask_price = current_price + spread_amount
        return (bid_price, ask_price)

    def place_order(self, side: str, price: float) -> Optional[OrderInfo]:
        """
        Place a limit order.

        Args:
            side: "buy" or "sell"
            price: Order price

        Returns:
            OrderInfo if successful, None otherwise
        """
        try:
            cl_ord_id = f"{side}_{int(time.time() * 1000)}"

            response = self.http_client.place_order(
                token=self.token,
                symbol=self.symbol,
                side=side,
                order_type="limit",
                qty=self.order_size,
                price=str(price),
                time_in_force="gtc",
                reduce_only=False,
                cl_ord_id=cl_ord_id,
                margin_mode=self.margin_mode,
                leverage=self.leverage,
                auth=self.auth
            )

            logger.info(f"Placed {side} order at {price}: {response}")

            # Note: Extract order_id from response (adjust based on actual API response)
            # For now, we'll track by cl_ord_id
            order_info = OrderInfo(
                order_id=0,  # Will be updated when we query orders
                side=side,
                price=price,
                qty=float(self.order_size),
                cl_ord_id=cl_ord_id
            )

            return order_info

        except Exception as e:
            logger.error(f"Failed to place {side} order: {e}")
            return None

    def cancel_all_orders(self) -> bool:
        """
        Cancel all active orders.

        Returns:
            True if successful
        """
        try:
            if not self.active_orders:
                return True

            order_ids = [order.order_id for order in self.active_orders.values() if order.order_id > 0]

            if order_ids:
                self.http_client.cancel_orders(
                    token=self.token,
                    order_id_list=order_ids,
                    auth=self.auth
                )
                logger.info(f"Cancelled {len(order_ids)} orders")

            self.active_orders.clear()
            return True

        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
            return False

    def sync_open_orders(self):
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
                order_id = order_data.get("id")
                if order_id:
                    order_info = OrderInfo(
                        order_id=order_id,
                        side=order_data.get("side"),
                        price=float(order_data.get("price", 0)),
                        qty=float(order_data.get("qty", 0)),
                        cl_ord_id=order_data.get("cl_ord_id")
                    )
                    new_active_orders[order_id] = order_info

            self.active_orders = new_active_orders
            logger.debug(f"Synced {len(self.active_orders)} open orders")

        except Exception as e:
            logger.error(f"Failed to sync orders: {e}")

    def should_cancel_and_replace(self, current_price: float) -> bool:
        """
        Check if orders should be cancelled and replaced.

        Args:
            current_price: Current market price

        Returns:
            True if orders need updating
        """
        if not self.active_orders:
            return True

        # Check if any order is too close to current price
        for order in self.active_orders.values():
            price_diff_pct = abs(order.price - current_price) / current_price

            # If order is within cancel threshold, cancel and replace
            if price_diff_pct < self.cancel_threshold:
                logger.info(f"Order at {order.price} too close to market {current_price}, will cancel")
                return True

        return False

    def run_strategy_loop(self):
        """Main strategy loop"""
        logger.info("Starting market making strategy loop")

        while True:
            try:
                # Get current price
                current_price = self.get_current_price()
                if not current_price:
                    logger.warning("Could not get current price, retrying...")
                    time.sleep(self.check_interval)
                    continue

                logger.info(f"Current price: {current_price}")

                # Sync open orders
                self.sync_open_orders()

                # Check if we need to cancel and replace orders
                if self.should_cancel_and_replace(current_price):
                    logger.info("Cancelling existing orders...")
                    self.cancel_all_orders()

                    # Calculate new order prices
                    bid_price, ask_price = self.calculate_order_prices(current_price)

                    logger.info(f"Placing new orders: Bid @ {bid_price}, Ask @ {ask_price}")

                    # Place bid order
                    bid_order = self.place_order("buy", bid_price)
                    if bid_order:
                        self.active_orders[bid_order.cl_ord_id] = bid_order

                    # Place ask order
                    ask_order = self.place_order("sell", ask_price)
                    if ask_order:
                        self.active_orders[ask_order.cl_ord_id] = ask_order

                    time.sleep(1)  # Brief pause between operations

                # Wait for next check
                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                logger.info("Received stop signal, cancelling all orders...")
                self.cancel_all_orders()
                break
            except Exception as e:
                logger.error(f"Error in strategy loop: {e}", exc_info=True)
                time.sleep(self.check_interval)

    def start(self):
        """Start the market making bot"""
        logger.info("Starting StandX Market Maker...")

        # Login
        if not self.login():
            logger.error("Failed to login, exiting")
            return

        # Run strategy
        self.run_strategy_loop()


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load config
    config = get_config()

    # Create and start market maker
    mm = StandXMarketMaker(config)
    mm.start()
