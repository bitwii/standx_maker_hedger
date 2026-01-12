"""
Arbitrage Bot Package
Market making on StandX with Lighter hedging
"""

__version__ = "1.0.0"
__author__ = "Your Name"

from .config_loader import get_config
from .arbitrage_bot import ArbitrageBot
from .standx_market_maker import StandXMarketMaker
from .lighter_client import LighterHedger
from .risk_manager import RiskManager

__all__ = [
    "get_config",
    "ArbitrageBot",
    "StandXMarketMaker",
    "LighterHedger",
    "RiskManager"
]
