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
        self.hedge_immediately = self.config.get("strategy.hedge_immediately", True)
        self.spread_pct = self.config.get("trading.spread_percentage", 0.1) / 100.0
        self.cancel_threshold = self.config.get("strategy.cancel_distance_percentage", 0.05) / 100.0
        self.check_interval = self.config.get("trading.check_interval_seconds", 5)
        self.order_size = Decimal(self.config.get("trading.order_size", "0.01"))

        # State tracking
        self.running = False
        self.current_price = None

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

            # Place hedge on Lighter
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
                else:
                    logger.error("FAILED TO HEDGE! Manual intervention required!")
                    self.risk_mgr.force_stop()

        except Exception as e:
            logger.error(f"Error handling fill: {e}", exc_info=True)
            self.risk_mgr.force_stop()

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

            # Calculate order prices
            spread_amount = mark_price * Decimal(str(self.spread_pct))
            # Round prices to integers for StandX price tick requirement
            bid_price = float(int(mark_price - spread_amount))
            ask_price = float(int(mark_price + spread_amount))

            logger.info(f"Placing orders: Bid @ {bid_price}, Ask @ {ask_price}")

            # Check if we can place orders
            if not self.risk_mgr.can_place_order(len(self.standx.active_orders)):
                logger.warning("Max orders limit reached")
                return

            # Place bid order
            bid_order = await self.standx.place_order("buy", bid_price, float(self.order_size))
            if bid_order:
                logger.info(f"Bid order placed: {bid_order.order_id}")

            # Place ask order
            ask_order = await self.standx.place_order("sell", ask_price, float(self.order_size))
            if ask_order:
                logger.info(f"Ask order placed: {ask_order.order_id}")

        except Exception as e:
            logger.error(f"Error placing orders: {e}", exc_info=True)

    async def check_and_update_orders(self):
        """Check if orders need to be cancelled and replaced"""
        try:
            # Get current price
            ticker = self.standx.get_ticker()
            mark_price = Decimal(str(ticker.get("mark_price", 0)))

            if mark_price <= 0:
                return

            self.current_price = mark_price

            # Sync open orders
            await self.standx.sync_open_orders()

            # Check if any order is too close to current price
            needs_update = False
            for order_id, order_info in self.standx.active_orders.items():
                price_diff_pct = abs(Decimal(str(order_info.price)) - mark_price) / mark_price

                if price_diff_pct < Decimal(str(self.cancel_threshold)):
                    logger.info(f"Order {order_id} at {order_info.price} too close to market {mark_price}")
                    needs_update = True
                    break

            # If orders need updating, cancel all and replace
            if needs_update or len(self.standx.active_orders) == 0:
                logger.info("Cancelling and replacing orders...")

                # Cancel all orders
                if len(self.standx.active_orders) > 0:
                    await self.standx.cancel_orders()
                    await asyncio.sleep(1)  # Brief pause

                # Place new orders
                await self.place_market_making_orders()

        except Exception as e:
            logger.error(f"Error checking orders: {e}", exc_info=True)

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

            last_status_print = 0

            while self.running:
                # Check emergency stop
                if self.risk_mgr.emergency_stop:
                    logger.error("EMERGENCY STOP TRIGGERED - Shutting down")
                    break

                # Check and update orders
                await self.check_and_update_orders()

                # Print status periodically
                current_time = asyncio.get_event_loop().time()
                if current_time - last_status_print > 60:  # Every 60 seconds
                    await self.print_status()
                    last_status_print = current_time

                # Sleep before next iteration
                await asyncio.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nReceived shutdown signal...")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def print_status(self):
        """Print bot status"""
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

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )


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
