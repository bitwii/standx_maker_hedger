"""
Risk Management Module
Monitors positions, P&L, and enforces risk limits
"""
import logging
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk management for arbitrage bot"""

    def __init__(self, config):
        """
        Initialize risk manager.

        Args:
            config: Config instance
        """
        self.config = config

        # Risk limits
        self.max_position_size = config.get_max_position_size()
        self.max_daily_loss = config.get_max_daily_loss()
        self.min_profit_threshold = config.get("risk_management.min_profit_threshold", 5.0)
        self.emergency_stop_loss = config.get("risk_management.emergency_stop_loss", 1000.0)
        self.max_open_orders = config.get("risk_management.max_open_orders", 10)

        # Tracking
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.trade_count = 0
        self.last_reset_date = datetime.now().date()

        # Emergency stop flag
        self.emergency_stop = False

        logger.info(f"Risk Manager initialized:")
        logger.info(f"  Max Position Size: {self.max_position_size}")
        logger.info(f"  Max Daily Loss: {self.max_daily_loss}")
        logger.info(f"  Emergency Stop Loss: {self.emergency_stop_loss}")

    def reset_daily_counters(self):
        """Reset daily P&L if new day"""
        current_date = datetime.now().date()
        if current_date > self.last_reset_date:
            logger.info(f"New day, resetting daily P&L. Previous: {self.daily_pnl}")
            self.daily_pnl = 0.0
            self.last_reset_date = current_date

    def update_pnl(self, pnl: float):
        """
        Update P&L tracking.

        Args:
            pnl: Realized P&L from trade
        """
        self.reset_daily_counters()
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.trade_count += 1

        logger.info(f"P&L Update: Trade={pnl:.2f}, Daily={self.daily_pnl:.2f}, Total={self.total_pnl:.2f}")

        # Check emergency stop
        self.check_emergency_stop()

    def check_emergency_stop(self):
        """Check if emergency stop should be triggered"""
        # Check daily loss limit
        if self.daily_pnl <= -self.max_daily_loss:
            logger.error(f"EMERGENCY STOP: Daily loss limit reached! Loss: {self.daily_pnl}")
            self.emergency_stop = True

        # Check total loss limit
        if self.total_pnl <= -self.emergency_stop_loss:
            logger.error(f"EMERGENCY STOP: Total loss limit reached! Loss: {self.total_pnl}")
            self.emergency_stop = True

    def can_open_position(self, position_size: float) -> bool:
        """
        Check if we can open a position of given size.

        Args:
            position_size: Proposed position size

        Returns:
            True if within limits
        """
        if self.emergency_stop:
            logger.warning("Emergency stop active, cannot open position")
            return False

        if abs(position_size) > self.max_position_size:
            logger.warning(f"Position size {position_size} exceeds limit {self.max_position_size}")
            return False

        self.reset_daily_counters()

        if self.daily_pnl <= -self.max_daily_loss:
            logger.warning(f"Daily loss limit reached: {self.daily_pnl}")
            return False

        return True

    def can_place_order(self, current_open_orders: int) -> bool:
        """
        Check if we can place another order.

        Args:
            current_open_orders: Number of currently open orders

        Returns:
            True if within limits
        """
        if self.emergency_stop:
            logger.warning("Emergency stop active, cannot place order")
            return False

        if current_open_orders >= self.max_open_orders:
            logger.warning(f"Max open orders limit reached: {current_open_orders}")
            return False

        return True

    def is_profitable_hedge(self, entry_price: float, exit_price: float, quantity: float) -> bool:
        """
        Check if hedging trade would be profitable.

        Args:
            entry_price: Entry price on StandX
            exit_price: Expected exit price on Lighter
            quantity: Trade quantity

        Returns:
            True if expected profit exceeds threshold
        """
        pnl = (exit_price - entry_price) * quantity
        if abs(pnl) < self.min_profit_threshold:
            logger.info(f"Trade profit {pnl:.2f} below threshold {self.min_profit_threshold}")
            return False

        return True

    def get_status(self) -> Dict:
        """
        Get risk manager status.

        Returns:
            Dictionary with status information
        """
        self.reset_daily_counters()

        return {
            "emergency_stop": self.emergency_stop,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "trade_count": self.trade_count,
            "max_daily_loss": self.max_daily_loss,
            "max_position_size": self.max_position_size,
            "daily_loss_remaining": self.max_daily_loss + self.daily_pnl
        }

    def force_stop(self):
        """Force emergency stop"""
        logger.error("FORCED EMERGENCY STOP")
        self.emergency_stop = True

    def reset_emergency_stop(self):
        """Reset emergency stop (use with caution)"""
        logger.warning("Resetting emergency stop flag")
        self.emergency_stop = False
