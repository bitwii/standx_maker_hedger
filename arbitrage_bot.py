"""
Main Arbitrage Bot Controller
Coordinates StandX market making, Lighter hedging, and risk management
"""
import logging
import time
import sys
from typing import Optional, Dict
from datetime import datetime

from config_loader import get_config
from standx_market_maker import StandXMarketMaker, OrderInfo
from lighter_client import LighterHedger
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


class ArbitrageBot:
    """Main arbitrage bot controller"""

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
        self.rebalance_on_fill = self.config.get("strategy.rebalance_on_fill", True)

        # State tracking
        self.running = False
        self.last_fill_check = time.time()
        self.filled_orders: Dict[str, OrderInfo] = {}

        logger.info("Arbitrage bot initialized successfully")

    def check_for_fills(self):
        """
        Check if any StandX orders were filled and handle hedging.
        """
        try:
            # Get current open orders
            self.standx.sync_open_orders()

            # Compare with previous state to detect fills
            current_order_ids = set(self.standx.active_orders.keys())

            # Check if any tracked orders are no longer open (possibly filled)
            for order_id, order_info in list(self.filled_orders.items()):
                if order_id not in current_order_ids:
                    # Order no longer open, likely filled
                    logger.info(f"Detected fill: {order_info.side} {order_info.qty} @ {order_info.price}")

                    # Handle the fill
                    self.handle_fill(order_info)

                    # Remove from tracking
                    del self.filled_orders[order_id]

            # Update tracking with current orders
            self.filled_orders = self.standx.active_orders.copy()

        except Exception as e:
            logger.error(f"Error checking for fills: {e}", exc_info=True)

    def handle_fill(self, filled_order: OrderInfo):
        """
        Handle a filled order by hedging on Lighter.

        Args:
            filled_order: Information about the filled order
        """
        try:
            # Check risk limits
            if not self.risk_mgr.can_open_position(filled_order.qty):
                logger.error("Risk limits prevent hedging, MANUAL INTERVENTION REQUIRED!")
                self.risk_mgr.force_stop()
                return

            # Determine hedge side (opposite of filled order)
            hedge_side = "sell" if filled_order.side == "buy" else "buy"

            logger.info(f"Hedging filled order: {filled_order.side} -> Lighter {hedge_side}")

            # Place hedge on Lighter
            if self.hedge_immediately:
                success = self.lighter.place_hedge_order(
                    side=hedge_side,
                    quantity=filled_order.qty,
                    price=None  # Market order for immediate fill
                )

                if success:
                    logger.info("Hedge placed successfully")

                    # Calculate approximate P&L (would need more precise tracking)
                    # For now, log as neutral since we're hedged
                    self.risk_mgr.update_pnl(0.0)
                else:
                    logger.error("FAILED TO HEDGE! Manual intervention required!")
                    self.risk_mgr.force_stop()

        except Exception as e:
            logger.error(f"Error handling fill: {e}", exc_info=True)
            self.risk_mgr.force_stop()

    def run(self):
        """Main bot execution loop"""
        logger.info("=" * 60)
        logger.info("Starting Arbitrage Bot")
        logger.info("=" * 60)

        # Pre-flight checks
        logger.info("Running pre-flight checks...")

        # Login to StandX
        if not self.standx.login():
            logger.error("Failed to login to StandX, exiting")
            return

        # Connect to Lighter
        if self.lighter.enabled:
            if not self.lighter.connect():
                logger.warning("Failed to connect to Lighter, hedging will be disabled")
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
            while self.running:
                # Check emergency stop
                if self.risk_mgr.emergency_stop:
                    logger.error("EMERGENCY STOP TRIGGERED - Shutting down")
                    break

                # Get current price
                current_price = self.standx.get_current_price()
                if not current_price:
                    logger.warning("Could not get price, retrying...")
                    time.sleep(self.standx.check_interval)
                    continue

                # Sync and check for fills
                self.check_for_fills()

                # Let StandX market maker manage orders
                # (We could call standx methods directly or let it run its own loop)
                # For now, we'll check if we should cancel and replace
                if self.standx.should_cancel_and_replace(current_price):
                    # Check if we can place orders
                    if self.risk_mgr.can_place_order(len(self.standx.active_orders)):
                        logger.info("Updating orders...")
                        self.standx.cancel_all_orders()

                        bid_price, ask_price = self.standx.calculate_order_prices(current_price)

                        # Place new orders
                        bid_order = self.standx.place_order("buy", bid_price)
                        if bid_order:
                            self.standx.active_orders[bid_order.cl_ord_id] = bid_order
                            self.filled_orders[bid_order.cl_ord_id] = bid_order

                        ask_order = self.standx.place_order("sell", ask_price)
                        if ask_order:
                            self.standx.active_orders[ask_order.cl_ord_id] = ask_order
                            self.filled_orders[ask_order.cl_ord_id] = ask_order

                # Print status
                if int(time.time()) % 60 == 0:  # Every minute
                    self.print_status()

                # Sleep before next iteration
                time.sleep(self.standx.check_interval)

        except KeyboardInterrupt:
            logger.info("\nReceived shutdown signal...")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()

    def print_status(self):
        """Print bot status"""
        risk_status = self.risk_mgr.get_status()
        lighter_pos = self.lighter.get_position()

        logger.info("=" * 60)
        logger.info(f"Bot Status at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Current Price: {self.standx.current_price}")
        logger.info(f"  Open Orders: {len(self.standx.active_orders)}")
        logger.info(f"  Lighter Position: {lighter_pos}")
        logger.info(f"  Daily P&L: ${risk_status['daily_pnl']:.2f}")
        logger.info(f"  Total P&L: ${risk_status['total_pnl']:.2f}")
        logger.info(f"  Trade Count: {risk_status['trade_count']}")
        logger.info(f"  Emergency Stop: {risk_status['emergency_stop']}")
        logger.info("=" * 60)

    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down bot...")
        self.running = False

        # Cancel all open orders
        logger.info("Cancelling all open orders on StandX...")
        self.standx.cancel_all_orders()

        # Optionally close Lighter position
        if self.config.get("strategy.close_position_on_shutdown", False):
            logger.info("Closing Lighter position...")
            self.lighter.close_position()

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


def main():
    """Main entry point"""
    # Load config
    config = get_config()

    # Setup logging
    setup_logging(config)

    logger.info("Starting Arbitrage Bot System")

    # Create and run bot
    bot = ArbitrageBot()
    bot.run()


if __name__ == "__main__":
    main()
