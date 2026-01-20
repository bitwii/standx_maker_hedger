"""
StandX Maker Hedger - Main Controller
Market making on StandX with Lighter hedging
"""
import logging
import asyncio
import sys
from decimal import Decimal
from datetime import datetime

from config_loader import get_config
from standx_client import StandXMarketMaker
from lighter_client import LighterHedger
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


class StandXMakerHedger:
    """StandX Maker Hedger - Market making with hedging controller"""

    def __init__(self, config_path: str = "config.json", env_path: str = ".env"):
        """
        Initialize arbitrage bot.

        Args:
            config_path: Path to config file
            env_path: Path to .env file
        """
        # Load configuration
        self.config = get_config(config_path, env_path)

        # Initialize components
        logger.info("Initializing bot components...")

        self.standx = StandXMarketMaker(self.config)
        self.lighter = LighterHedger(self.config)
        self.risk_mgr = RiskManager(self.config)

        # Strategy settings
        # 订单成交后是否立即对冲
        self.hedge_immediately = self.config.get("strategy.hedge_immediately", True)
        # 市场价移动到距离当前挂单多少时撤单
        self.spread_pct = self.config.get("trading.spread_percentage", 0.1) / 100.0
        self.cancel_threshold = self.config.get("strategy.cancel_distance_percentage", 0.05) / 100.0
        self.check_interval = self.config.get("trading.check_interval_seconds", 5)
        self.order_size = Decimal(self.config.get("trading.order_size", "0.01"))

        # Close position settings
        self.close_spread_pct = self.config.get("strategy.close_spread_percentage", 0.01) / 100.0
        self.close_update_threshold = self.config.get("strategy.close_order_update_threshold", 0.05) / 100.0

        # State tracking
        self.running = False
        self.current_price = None

        # Close order tracking
        self.close_order_id = None  # Track the close order (real order ID from WebSocket)
        self.close_order_cl_ord_id = None  # Track client order ID
        self.close_order_price = None  # Track close order price for adjustment
        self.close_order_side = None  # Track close order side

        # Status tracking for smart logging
        self.last_status = {
            'standx_pos': 0,
            'lighter_pos': 0,
            'order_count': 0,
            'trade_count': 0,
            'pnl': 0.0
        }
        self.last_hourly_status_time = 0

        # Loop protection for Lighter position closing
        self.lighter_close_attempts = {}  # Track close attempts per position
        self.max_close_attempts = 10  # Maximum attempts before requiring manual intervention
        self.lighter_close_blocked = set()  # Positions that have exceeded max attempts

        logger.info("StandX Maker Hedger initialized successfully")

    async def handle_standx_order_fill(self, order_data: dict):
        """
        Handle StandX order fill by hedging on Lighter.

        Args:
            order_data: Order fill data from WebSocket
        """
        try:
            order_id = order_data.get("order_id")
            side = order_data.get("side")  # "buy" or "sell"
            filled_qty = Decimal(str(order_data.get("qty", 0)))
            fill_price = Decimal(str(order_data.get("price", 0)))

            logger.info(f"Detected StandX fill: {side} {filled_qty}@{fill_price}")

            # Check risk limits before hedging
            if not self.risk_mgr.can_open_position(float(filled_qty)):
                logger.error("Risk limits prevent hedging, MANUAL INTERVENTION REQUIRED!")
                self.risk_mgr.force_stop()
                return

            # Determine hedge side (opposite of StandX fill)
            hedge_side = "sell" if side == "buy" else "buy"

            logger.info(f"Hedging on Lighter: {hedge_side} {filled_qty}")

            # Place hedge on Lighter，判断，如果有配置立即对冲，就执行对冲
            if self.hedge_immediately:
                success = await self.lighter.place_hedge_order(
                    side=hedge_side,
                    quantity=filled_qty,
                    price=None  # Market price
                )

                if success:
                    logger.info("Hedge placed successfully")

                    # Calculate P&L (simplified - actual P&L depends on fill prices)
                    # For now, just track that we're hedged
                    self.risk_mgr.update_pnl(0.0)

                    # Place close order on StandX (Maker order to close the position)
                    # Close side is same as hedge side (opposite of original fill)
                    await self.place_close_order(side=hedge_side, quantity=filled_qty)
                else:
                    logger.error("FAILED TO HEDGE! Manual intervention required!")
                    self.risk_mgr.force_stop()

        except Exception as e:
            logger.error(f"Error handling fill: {e}", exc_info=True)
            self.risk_mgr.force_stop()

    async def place_close_order(self, side: str, quantity: Decimal):
        """
        Place a Maker order to close the position.

        Args:
            side: "buy" or "sell" (opposite of the original fill)
            quantity: Quantity to close
        """
        try:
            # Get current price
            ticker = self.standx.get_ticker()
            mark_price = Decimal(str(ticker.get("mark_price", 0)))

            if mark_price <= 0:
                logger.error("Invalid mark price, cannot place close order")
                return

            # Calculate close order price (1 bps away from mark price)
            close_spread = mark_price * Decimal(str(self.close_spread_pct))

            if side == "buy":
                # For buy close order, place slightly below mark (easier to fill)
                close_price = float(int(mark_price - close_spread))
            else:  # sell
                # For sell close order, place slightly above mark (easier to fill)
                close_price = float(int(mark_price + close_spread))

            logger.info(f"→ Placing CLOSE order on StandX: {side.upper()} {quantity} @ ${close_price:,.2f} (Maker)")

            # Place close order
            order = await self.standx.place_order(side, close_price, float(quantity))

            if order:
                # Mark this order as a close order (should NOT trigger hedge when filled)
                self.standx.mark_as_close_order(order.order_id)

                # Save cl_ord_id for tracking (real order_id will come from WebSocket)
                self.close_order_cl_ord_id = order.cl_ord_id
                self.close_order_price = Decimal(str(close_price))
                self.close_order_side = side
                logger.info(f"✓ Close order placed: cl_ord_id={order.cl_ord_id}")
            else:
                logger.error("Failed to place close order")

        except Exception as e:
            logger.error(f"Error placing close order: {e}", exc_info=True)

    async def place_market_making_orders(self):
        """Place bid and ask orders around current price"""
        try:
            # Get current price
            ticker = self.standx.get_ticker()
            mark_price = Decimal(str(ticker.get("mark_price", 0)))

            if mark_price <= 0:
                logger.warning("Invalid mark price, skipping order placement")
                return

            self.current_price = mark_price

            # Calculate order prices， 是spread_percentage这个配置变量
            spread_amount = mark_price * Decimal(str(self.spread_pct))
            # Round prices to integers for StandX price tick requirement
            bid_price = float(int(mark_price - spread_amount))
            ask_price = float(int(mark_price + spread_amount))

            # Check if we can place orders
            if not self.risk_mgr.can_place_order(len(self.standx.active_orders)):
                logger.warning("Max orders limit reached")
                return

            # Place bid order
            bid_order = await self.standx.place_order("buy", bid_price, float(self.order_size))
            if bid_order:
                symbol = self.standx.symbol.split('-')[0]  # e.g., "BTC"
                logger.info(f"✓ Bid placed: {symbol} @ ${bid_price:,.2f}")

            # Place ask order
            ask_order = await self.standx.place_order("sell", ask_price, float(self.order_size))
            if ask_order:
                symbol = self.standx.symbol.split('-')[0]  # e.g., "BTC"
                logger.info(f"✓ Ask placed: {symbol} @ ${ask_price:,.2f}")

        except Exception as e:
            logger.error(f"Error placing orders: {e}", exc_info=True)

    async def check_and_update_orders(self):
        """Check if orders need to be cancelled and replaced"""
        try:
            # Get current price,调用StandX的ticker接口获取最新当前
            ticker = self.standx.get_ticker()
            mark_price = Decimal(str(ticker.get("mark_price", 0)))

            if mark_price <= 0:
                return

            self.current_price = mark_price

            # Sync open orders
            await self.standx.sync_open_orders()

            # Check if any order is too close to current price
            needs_update = False
            for _, order_info in self.standx.active_orders.items():
                price_diff_pct = abs(Decimal(str(order_info.price)) - mark_price) / mark_price

                if price_diff_pct < Decimal(str(self.cancel_threshold)):
                    side = "Bid" if order_info.side == "buy" else "Ask"
                    logger.info(f"{side} ${order_info.price:,.2f} too close to ${mark_price:,.2f}")
                    needs_update = True
                    break

            # If orders need updating, cancel all and replace
            if needs_update or len(self.standx.active_orders) == 0:
                # Cancel all orders
                if len(self.standx.active_orders) > 0:
                    await self.standx.cancel_orders()
                    await asyncio.sleep(1)  # Brief pause

                # Place new orders
                await self.place_market_making_orders()

        except Exception as e:
            logger.error(f"Error checking orders: {e}", exc_info=True)

    async def check_and_manage_close_orders(self):
        """
        Check if we have open positions that need closing.
        Manage close orders by adjusting them if price moves significantly.
        """
        try:
            # Get current positions
            standx_pos = await self.standx.get_position()
            lighter_pos = await self.lighter.get_position() if self.lighter.enabled else Decimal('0')

            # If no positions, clear close order tracking
            if standx_pos == 0 and lighter_pos == 0:
                if self.close_order_cl_ord_id:
                    self.close_order_id = None
                    self.close_order_cl_ord_id = None
                    self.close_order_price = None
                    self.close_order_side = None
                return

            # If we have positions but no close order, something went wrong
            if (standx_pos != 0 or lighter_pos != 0) and not self.close_order_cl_ord_id:
                logger.warning(f"Have positions (SX={standx_pos}, LT={lighter_pos}) but no close order tracked")

                # Handle StandX position
                if standx_pos > 0:
                    await self.place_close_order(side="sell", quantity=abs(standx_pos))
                elif standx_pos < 0:
                    await self.place_close_order(side="buy", quantity=abs(standx_pos))
                # Handle Lighter-only position (StandX already closed but Lighter still open)
                elif standx_pos == 0 and lighter_pos != 0:
                    # Check loop protection
                    pos_key = f"{lighter_pos:.5f}"

                    # Check if this position is blocked from further attempts
                    if pos_key in self.lighter_close_blocked:
                        # Silently skip - already logged the error
                        return

                    attempts = self.lighter_close_attempts.get(pos_key, 0)

                    if attempts >= self.max_close_attempts:
                        logger.error(f"CRITICAL: Failed to close Lighter position {lighter_pos} BTC after {attempts} attempts")
                        logger.error("MANUAL INTERVENTION REQUIRED - Stopping auto-close attempts for this position")
                        logger.error("Please manually close the Lighter position and restart the bot")
                        # Block further attempts for this position
                        self.lighter_close_blocked.add(pos_key)
                        return

                    self.lighter_close_attempts[pos_key] = attempts + 1
                    logger.warning(f"StandX position is 0 but Lighter has {lighter_pos} BTC (attempt {attempts + 1}/{self.max_close_attempts})")
                    await self.close_lighter_hedge(lighter_pos)

                    # If close was successful, reset the counter
                    # Re-check position after close attempt
                    await asyncio.sleep(1)
                    new_lighter_pos = await self.lighter.get_position()
                    if new_lighter_pos == 0:
                        # Successfully closed, clear the attempt counter
                        if pos_key in self.lighter_close_attempts:
                            del self.lighter_close_attempts[pos_key]
                        if pos_key in self.lighter_close_blocked:
                            self.lighter_close_blocked.remove(pos_key)
                        logger.info("✓ Lighter position successfully closed, cleared attempt counter")

                return

            # If we have a close order, check if it needs adjustment
            if self.close_order_cl_ord_id and self.close_order_price and self.close_order_side:
                # Get current price
                ticker = self.standx.get_ticker()
                mark_price = Decimal(str(ticker.get("mark_price", 0)))

                if mark_price <= 0:
                    return

                # Check if close order still exists in active orders (by cl_ord_id)
                await self.standx.sync_open_orders()

                # Find order by cl_ord_id
                close_order_exists = False
                close_order_real_id = None
                for order_id, order_info in self.standx.active_orders.items():
                    if order_info.cl_ord_id == self.close_order_cl_ord_id:
                        close_order_exists = True
                        close_order_real_id = order_id
                        # Update real order_id if we haven't saved it yet
                        if not self.close_order_id:
                            self.close_order_id = order_id
                            # Mark this order as a close order
                            self.standx.mark_as_close_order(order_id)
                        break

                if not close_order_exists:
                    # Close order was filled or cancelled
                    logger.info(f"Close order (cl_ord_id={self.close_order_cl_ord_id}) no longer active")

                    # Check if position is closed
                    standx_pos_after = await self.standx.get_position()

                    if standx_pos_after == 0:
                        # Position closed! Now close Lighter hedge
                        logger.info("✓ StandX position closed via Maker order!")
                        await self.close_lighter_hedge(lighter_pos)

                        # Clear close order tracking
                        self.close_order_id = None
                        self.close_order_cl_ord_id = None
                        self.close_order_price = None
                        self.close_order_side = None
                    else:
                        # Order was cancelled but position still open, place new close order
                        logger.warning("Close order cancelled but position still open, replacing...")
                        if standx_pos_after > 0:
                            await self.place_close_order(side="sell", quantity=abs(standx_pos_after))
                        elif standx_pos_after < 0:
                            await self.place_close_order(side="buy", quantity=abs(standx_pos_after))

                    return

                # Check if price has moved significantly in the favorable direction
                # For sell close order: if price rises, adjust order upward
                # For buy close order: if price falls, adjust order downward
                price_diff = mark_price - self.close_order_price
                price_diff_pct = abs(price_diff) / mark_price

                needs_adjustment = False

                if self.close_order_side == "sell" and price_diff > 0:
                    # Price rose, sell order should be adjusted higher
                    if price_diff_pct > Decimal(str(self.close_update_threshold)):
                        logger.info(f"Price rose from ${self.close_order_price:,.2f} to ${mark_price:,.2f}, adjusting sell close order")
                        needs_adjustment = True
                elif self.close_order_side == "buy" and price_diff < 0:
                    # Price fell, buy order should be adjusted lower
                    if price_diff_pct > Decimal(str(self.close_update_threshold)):
                        logger.info(f"Price fell from ${self.close_order_price:,.2f} to ${mark_price:,.2f}, adjusting buy close order")
                        needs_adjustment = True

                if needs_adjustment:
                    # Cancel current close order and place new one
                    logger.info(f"Cancelling close order {self.close_order_id} for adjustment")
                    await self.standx.cancel_order(self.close_order_id)
                    await asyncio.sleep(0.5)  # Brief pause

                    # Place new close order at current price
                    if standx_pos > 0:
                        await self.place_close_order(side="sell", quantity=abs(standx_pos))
                    elif standx_pos < 0:
                        await self.place_close_order(side="buy", quantity=abs(standx_pos))

        except Exception as e:
            logger.error(f"Error managing close orders: {e}", exc_info=True)

    async def close_lighter_hedge(self, lighter_pos: Decimal, max_retries: int = 3):
        """
        Close the Lighter hedge position after StandX position is closed.
        Implements retry logic for handling margin errors and transient failures.
        Uses market orders since Lighter has no fees.

        Args:
            lighter_pos: Current Lighter position
            max_retries: Maximum number of retry attempts (default: 3)
        """
        try:
            if lighter_pos == 0:
                logger.info("No Lighter position to close")
                return

            # Determine close side (opposite of current position)
            # Positive position = long = need to SELL to close
            # Negative position = short = need to BUY to close
            close_side = "buy" if lighter_pos < 0 else "sell"
            close_qty = abs(lighter_pos)

            logger.info(f"→ Closing Lighter hedge: {close_side.upper()} {close_qty} (current position: {lighter_pos})")

            # Retry loop for handling transient failures
            for attempt in range(1, max_retries + 1):
                # Close Lighter position using market order (no fees on Lighter)
                success = await self.lighter.place_market_close_order(
                    side=close_side,
                    quantity=close_qty
                )

                if success:
                    logger.info("✓ Lighter hedge close order submitted")

                    # Wait for order to be processed and verify position is closed
                    await asyncio.sleep(2)

                    # Re-fetch actual position from API
                    actual_pos = await self.lighter.get_position()

                    if actual_pos == 0:
                        logger.info("✓ Verified: Lighter position successfully closed (position = 0)")
                        return
                    else:
                        logger.warning(f"Position verification failed: {actual_pos} BTC still open after close attempt")
                        # Continue to retry
                        if attempt < max_retries:
                            wait_time = attempt * 2
                            logger.warning(f"Retrying close (attempt {attempt + 1}/{max_retries}) in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"Failed to close Lighter hedge after {max_retries} attempts")
                            logger.error(f"CRITICAL: Manual intervention required - Lighter position {actual_pos} BTC still open!")
                            return
                else:
                    if attempt < max_retries:
                        wait_time = attempt * 2  # Exponential backoff: 2s, 4s, 6s
                        logger.warning(f"Failed to close Lighter hedge (attempt {attempt}/{max_retries}), retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Failed to close Lighter hedge after {max_retries} attempts")
                        logger.error(f"CRITICAL: Manual intervention required - Lighter position {lighter_pos} BTC still open!")

        except Exception as e:
            logger.error(f"Error closing Lighter hedge: {e}", exc_info=True)
            logger.error(f"CRITICAL: Manual intervention required - Lighter position {lighter_pos} BTC may still be open!")


    async def run(self):
        """Main bot execution loop"""
        logger.info("=" * 60)
        logger.info("Starting StandX Maker Hedger")
        logger.info("=" * 60)

        # Pre-flight checks
        logger.info("Running pre-flight checks...")

        # Connect to StandX
        if not await self.standx.connect():
            logger.error("Failed to connect to StandX, exiting")
            return

        # Setup order fill handler
        self.standx.setup_order_update_handler(self.handle_standx_order_fill)

        # Connect to Lighter
        if self.lighter.enabled:
            if not await self.lighter.connect():
                logger.warning("Failed to connect to Lighter, hedging will be disabled")
                self.lighter.enabled = False
        else:
            logger.info("Lighter hedging is disabled in config")

        # Check risk status
        risk_status = self.risk_mgr.get_status()
        logger.info(f"Risk Status: {risk_status}")

        if risk_status["emergency_stop"]:
            logger.error("Emergency stop is active, cannot start bot")
            return

        logger.info("Pre-flight checks passed")
        logger.info("=" * 60)

        # Start main loop
        self.running = True

        try:
            # Place initial orders
            await self.place_market_making_orders()

            while self.running:
                # Check emergency stop
                if self.risk_mgr.emergency_stop:
                    logger.error("EMERGENCY STOP TRIGGERED - Shutting down")
                    break

                # Check and update orders， 这里会调用place_market_making_orders（）
                await self.check_and_update_orders()

                # Check and manage close orders (if we have open positions)
                await self.check_and_manage_close_orders()

                # Print status only if needed (changes or hourly)
                await self.print_status_if_needed()

                # Sleep before next iteration
                await asyncio.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nReceived shutdown signal...")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def print_status_if_needed(self):
        """
        Print bot status only if:
        1. Something changed (position, orders, trades, P&L)
        2. Or 1 hour has passed since last status print
        """
        try:
            import time
            current_time = time.time()

            # Get current status
            risk_status = self.risk_mgr.get_status()
            standx_pos = await self.standx.get_position()
            lighter_pos = await self.lighter.get_position()
            order_count = len(self.standx.active_orders)
            trade_count = risk_status['trade_count']
            total_pnl = risk_status['total_pnl']

            # Check if anything changed
            has_changes = (
                standx_pos != self.last_status['standx_pos'] or
                lighter_pos != self.last_status['lighter_pos'] or
                order_count != self.last_status['order_count'] or
                trade_count != self.last_status['trade_count'] or
                abs(total_pnl - self.last_status['pnl']) > 0.01
            )

            # Check if 1 hour has passed
            hour_passed = (current_time - self.last_hourly_status_time) >= 3600

            # Print if changes or hourly
            if has_changes or hour_passed:
                # Use compact single-line format with abbreviations
                # SX = StandX, LT = Lighter
                symbol = self.standx.symbol  # e.g., "BTC-USD"
                base_symbol = symbol.split('-')[0]  # e.g., "BTC"
                logger.info(
                    f"Status: ${self.current_price:,.2f} | "
                    f"Orders={order_count} | "
                    f"Pos: SX={standx_pos:.2f}{base_symbol} LT={lighter_pos:.2f}{base_symbol} | "
                    f"P&L=${total_pnl:.2f} | "
                    f"Trades={trade_count}"
                )

                # Update last status
                self.last_status = {
                    'standx_pos': standx_pos,
                    'lighter_pos': lighter_pos,
                    'order_count': order_count,
                    'trade_count': trade_count,
                    'pnl': total_pnl
                }

                # Update hourly timer if it was hourly print
                if hour_passed:
                    self.last_hourly_status_time = current_time

        except Exception as e:
            logger.error(f"Error checking status: {e}")

    async def print_status(self):
        """Print detailed bot status (called on demand or startup)"""
        try:
            risk_status = self.risk_mgr.get_status()
            standx_pos = await self.standx.get_position()
            lighter_pos = await self.lighter.get_position()

            logger.info("=" * 60)
            logger.info(f"Bot Status at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"  Current Price: {self.current_price}")
            logger.info(f"  Open Orders (StandX): {len(self.standx.active_orders)}")
            logger.info(f"  StandX Position: {standx_pos}")
            logger.info(f"  Lighter Position: {lighter_pos}")
            logger.info(f"  Daily P&L: ${risk_status['daily_pnl']:.2f}")
            logger.info(f"  Total P&L: ${risk_status['total_pnl']:.2f}")
            logger.info(f"  Trade Count: {risk_status['trade_count']}")
            logger.info(f"  Emergency Stop: {risk_status['emergency_stop']}")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Error printing status: {e}")

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down bot...")
        self.running = False

        # Cancel all open orders on StandX
        logger.info("Cancelling all open orders on StandX...")
        try:
            await self.standx.cancel_orders()
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")

        # Optionally close Lighter position
        if self.config.get("strategy.close_position_on_shutdown", False):
            logger.info("Closing Lighter position...")
            try:
                await self.lighter.close_position()
            except Exception as e:
                logger.error(f"Error closing position: {e}")

        # Disconnect from exchanges
        try:
            await self.standx.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting from StandX: {e}")

        try:
            await self.lighter.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting from Lighter: {e}")

        logger.info("Shutdown complete")


def setup_logging(config):
    """Setup logging configuration"""
    log_level = config.get("logging.log_level", "INFO")
    log_file = config.get("logging.log_file", "logs/arbitrage_bot.log")

    # Create logs directory if it doesn't exist
    import os
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Custom formatter with milliseconds
    class MillisecondFormatter(logging.Formatter):
        """Custom formatter that shows milliseconds (2 digits) in UTC+8 timezone"""
        def formatTime(self, record, datefmt=None):
            from datetime import datetime, timezone, timedelta
            # Convert to UTC+8 (Asia/Shanghai timezone)
            utc_time = datetime.fromtimestamp(record.created, tz=timezone.utc)
            beijing_time = utc_time + timedelta(hours=8)

            # Format: YYMMDD HH:MM:SS.ms (e.g., 260112 10:15:46.78)
            date_part = beijing_time.strftime("%y%m%d")
            time_part = beijing_time.strftime("%H:%M:%S")
            # Add 2-digit milliseconds
            ms = int(record.msecs / 10)  # Convert to centiseconds (2 digits)
            return f"{date_part} {time_part}.{ms:02d}"

    # Configure logging with optimized format
    # Format: [YYMMDD HH:MM:SS.ms] LEVEL [File:Line] Message
    # Example: [260112 12:34:56.78]INFO[main.py:123] Bot started
    formatter = MillisecondFormatter(
        '[%(asctime)s]%(levelname)s[%(filename)s:%(lineno)d] %(message)s'
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


async def main_async():
    """Async main entry point"""
    # Load config
    config = get_config()

    # Setup logging
    setup_logging(config)

    logger.info("Starting StandX Maker Hedger System")

    # Create and run bot
    bot = StandXMakerHedger()
    await bot.run()


def main():
    """Main entry point"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
