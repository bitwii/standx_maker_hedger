"""
Lighter Exchange Hedger Client

Configuration:
- API_KEY_PRIVATE_KEY: Lighter API key private key
- LIGHTER_ACCOUNT_INDEX: Lighter account index
- LIGHTER_API_KEY_INDEX: Lighter API key index
"""
import os
import asyncio
import time
import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

# Import Lighter SDK
try:
    from lighter import SignerClient, ApiClient, Configuration
    import lighter
    LIGHTER_AVAILABLE = True
except ImportError:
    LIGHTER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Lighter SDK not installed. Install with: pip install git+https://github.com/elliottech/lighter-python.git")

from config_loader import get_config

logger = logging.getLogger(__name__)


class OrderInfo:
    """Order information"""
    def __init__(self, order_id: str, side: str, size: Decimal, price: Decimal,
                 status: str, filled_size: Decimal = Decimal('0'),
                 remaining_size: Decimal = None):
        self.order_id = order_id
        self.side = side
        self.size = size
        self.price = price
        self.status = status
        self.filled_size = filled_size
        self.remaining_size = remaining_size or (size - filled_size)


class LighterHedger:
    """
    Lighter Exchange Hedger
    Based on cross-exchange-arbitrage implementation
    """

    def __init__(self, config):
        """
        Initialize Lighter hedger.

        Args:
            config: Config instance
        """
        if not LIGHTER_AVAILABLE:
            raise ImportError("Lighter SDK not available. Please install it first.")

        self.config = config
        self.enabled = config.get("exchanges.lighter.enabled", True)
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        # Lighter credentials from environment
        self.api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
        self.account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
        self.api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))

        if not self.api_key_private_key:
            raise ValueError("API_KEY_PRIVATE_KEY must be set in environment variables")

        # Ticker configuration
        self.ticker = config.get("trading.symbol", "BTC-USD")
        # Convert StandX format (BTC-USD) to Lighter format (BTC)
        self.ticker_symbol = self.ticker.split('-')[0] if '-' in self.ticker else self.ticker

        # Lighter clients
        self.lighter_client = None
        self.api_client = None

        # Market configuration (will be loaded on connect)
        self.market_id = None
        self.base_amount_multiplier = None
        self.price_multiplier = None
        self.tick_size = None

        # Position tracking
        self.current_position = Decimal('0')

        # Order tracking
        self.orders_cache = {}
        self.current_order = None

        logger.info(f"Initialized Lighter Hedger (enabled={self.enabled})")

    async def connect(self) -> bool:
        """
        Connect to Lighter exchange.

        Returns:
            True if successful
        """
        if not self.enabled:
            logger.info("Lighter hedging is disabled")
            return False

        try:
            logger.info("Connecting to Lighter...")

            # Initialize API client
            self.api_client = ApiClient(configuration=Configuration(host=self.base_url))

            # Initialize Lighter signer client
            await self._initialize_lighter_client()

            # Get market configuration
            await self._get_market_config()

            logger.info("Connected to Lighter successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Lighter: {e}")
            return False

    async def _initialize_lighter_client(self):
        """Initialize the Lighter client using official SDK"""
        if self.lighter_client is None:
            try:
                api_private_keys = {self.api_key_index: self.api_key_private_key}

                self.lighter_client = SignerClient(
                    url=self.base_url,
                    account_index=self.account_index,
                    api_private_keys=api_private_keys,
                )

                # Check client
                err = self.lighter_client.check_client()
                if err is not None:
                    raise Exception(f"CheckClient error: {err}")

                logger.info("Lighter client initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize Lighter client: {e}")
                raise

        return self.lighter_client

    async def _get_market_config(self):
        """Get market configuration for ticker"""
        try:
            order_api = lighter.OrderApi(self.api_client)
            order_books = await order_api.order_books()

            for market in order_books.order_books:
                if market.symbol == self.ticker_symbol:
                    self.market_id = market.market_id
                    self.base_amount_multiplier = pow(10, market.supported_size_decimals)
                    self.price_multiplier = pow(10, market.supported_price_decimals)
                    self.tick_size = Decimal("1") / Decimal(str(self.price_multiplier))

                    logger.info(
                        f"Market config for {self.ticker_symbol}: "
                        f"ID={self.market_id}, "
                        f"Base multiplier={self.base_amount_multiplier}, "
                        f"Price multiplier={self.price_multiplier}"
                    )
                    return

            raise Exception(f"Ticker {self.ticker_symbol} not found in available markets")

        except Exception as e:
            logger.error(f"Error getting market config: {e}")
            raise

    async def place_hedge_order(self, side: str, quantity: Decimal,
                               price: Optional[Decimal] = None) -> bool:
        """
        Place a hedge order on Lighter.

        Args:
            side: "buy" or "sell"
            quantity: Order quantity
            price: Limit price (if None, uses market order logic with best price)

        Returns:
            True if successful
        """
        if not self.enabled:
            logger.warning("Lighter hedging disabled, skipping hedge order")
            return False

        try:
            # Determine order side
            is_ask = True if side.lower() == 'sell' else False

            # Generate unique client order index
            client_order_index = int(time.time() * 1000) % 1000000

            # If no price specified, get best price from orderbook
            if price is None:
                best_bid, best_ask = await self.fetch_bbo_prices()
                price = best_ask if side.lower() == 'buy' else best_bid
                logger.info(f"Using market price for {side}: {price}")

            # Create order parameters
            order_params = {
                'market_index': self.market_id,
                'client_order_index': client_order_index,
                'base_amount': int(quantity * self.base_amount_multiplier),
                'price': int(price * self.price_multiplier),
                'is_ask': is_ask,
                'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
                'time_in_force': self.lighter_client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                'reduce_only': False,
                'trigger_price': 0,
            }

            logger.info(f"Placing Lighter hedge: {side} {quantity} @ {price}")

            # Submit order
            create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)

            if error is not None:
                logger.error(f"Lighter hedge order failed: {error}")
                return False

            logger.info(f"Lighter hedge order placed successfully (tx: {tx_hash})")

            # Update position tracking
            qty_signed = quantity if side.lower() == 'buy' else -quantity
            self.current_position += qty_signed

            return True

        except Exception as e:
            logger.error(f"Failed to place Lighter hedge order: {e}")
            return False

    async def fetch_bbo_prices(self) -> Tuple[Decimal, Decimal]:
        """
        Get best bid/offer from orderbook.

        Returns:
            Tuple of (best_bid, best_ask)
        """
        try:
            order_api = lighter.OrderApi(self.api_client)

            # Get orderbook
            orderbook_response = await order_api.order_book(market_id=self.market_id)

            if not orderbook_response or not orderbook_response.order_book:
                raise ValueError("Empty orderbook response")

            orderbook = orderbook_response.order_book

            # Get best prices
            best_bid = Decimal('0')
            best_ask = Decimal('0')

            if orderbook.bids and len(orderbook.bids) > 0:
                best_bid = Decimal(str(orderbook.bids[0].price))

            if orderbook.asks and len(orderbook.asks) > 0:
                best_ask = Decimal(str(orderbook.asks[0].price))

            if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
                raise ValueError(f"Invalid bid/ask prices: {best_bid}/{best_ask}")

            return best_bid, best_ask

        except Exception as e:
            logger.error(f"Failed to fetch BBO: {e}")
            raise

    async def get_position(self, symbol: str = None) -> Decimal:
        """
        Get current position on Lighter.

        Args:
            symbol: Trading symbol (uses config if None)

        Returns:
            Position size (positive for long, negative for short)
        """
        if not self.enabled:
            return Decimal('0')

        try:
            positions = await self._fetch_positions()

            # Find position for our market
            for position in positions:
                if position.market_id == self.market_id:
                    pos_size = Decimal(str(position.position))
                    self.current_position = pos_size
                    return pos_size

            return Decimal('0')

        except Exception as e:
            logger.error(f"Failed to get Lighter position: {e}")
            return Decimal('0')

    async def _fetch_positions(self):
        """Fetch positions from Lighter API"""
        try:
            account_api = lighter.AccountApi(self.api_client)
            auth_token, err = self.lighter_client.create_auth_token_with_expiry()

            if err is not None:
                raise Exception(f"Auth token error: {err}")

            positions_response = await account_api.user_positions(
                account_index=self.account_index,
                authorization=auth_token
            )

            return positions_response.positions if positions_response else []

        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    async def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order by ID.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if successful
        """
        try:
            cancel_result, error = await self.lighter_client.cancel_order(
                market_index=self.market_id,
                order_index=order_id
            )

            if error is not None:
                logger.error(f"Failed to cancel order {order_id}: {error}")
                return False

            logger.info(f"Cancelled order {order_id}")
            return True

        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    async def close_position(self, symbol: str = None) -> bool:
        """
        Close entire position on Lighter.

        Args:
            symbol: Trading symbol

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        try:
            position = await self.get_position(symbol)

            if abs(position) < Decimal('0.0001'):
                logger.info("No position to close on Lighter")
                return True

            # Determine side to close
            side = "sell" if position > 0 else "buy"
            quantity = abs(position)

            logger.info(f"Closing Lighter position: {side} {quantity}")

            # Get best price for closing
            best_bid, best_ask = await self.fetch_bbo_prices()
            close_price = best_bid if side == "sell" else best_ask

            # Place closing order
            success = await self.place_hedge_order(side, quantity, close_price)

            if success:
                self.current_position = Decimal('0')
                logger.info("Lighter position closed successfully")

            return success

        except Exception as e:
            logger.error(f"Failed to close Lighter position: {e}")
            return False

    async def get_balance(self) -> Dict[str, Decimal]:
        """
        Get account balance on Lighter.

        Returns:
            Dictionary with balance information
        """
        if not self.enabled:
            return {"balance": Decimal('0'), "available": Decimal('0')}

        try:
            account_api = lighter.AccountApi(self.api_client)
            auth_token, err = self.lighter_client.create_auth_token_with_expiry()

            if err is not None:
                raise Exception(f"Auth token error: {err}")

            balance_response = await account_api.user_balances(
                account_index=self.account_index,
                authorization=auth_token
            )

            if balance_response and balance_response.balances:
                # Usually USDC balance
                balance = Decimal(str(balance_response.balances[0].free))
                return {
                    "balance": balance,
                    "available": balance
                }

            return {"balance": Decimal('0'), "available": Decimal('0')}

        except Exception as e:
            logger.error(f"Failed to get Lighter balance: {e}")
            return {"balance": Decimal('0'), "available": Decimal('0')}

    async def disconnect(self):
        """Disconnect from Lighter"""
        try:
            if self.api_client:
                await self.api_client.close()
                self.api_client = None

            logger.info("Disconnected from Lighter")

        except Exception as e:
            logger.error(f"Error during Lighter disconnect: {e}")
