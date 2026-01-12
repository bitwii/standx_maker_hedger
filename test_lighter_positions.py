"""
Test script for Lighter position fetching
测试 Lighter 仓位获取功能
"""
import os
import asyncio
import logging
from decimal import Decimal
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_lighter_positions():
    """测试 Lighter 仓位获取"""
    try:
        # Import after setting up logging
        from lighter_client import LighterHedger
        from config_loader import get_config

        logger.info("=" * 60)
        logger.info("开始测试 Lighter 仓位获取功能")
        logger.info("=" * 60)

        # Check environment variables
        logger.info("\n1. 检查环境变量...")
        api_key = os.getenv('API_KEY_PRIVATE_KEY')
        account_index = os.getenv('LIGHTER_ACCOUNT_INDEX', '0')
        api_key_index = os.getenv('LIGHTER_API_KEY_INDEX', '0')

        if not api_key:
            logger.error("❌ API_KEY_PRIVATE_KEY 未设置")
            return

        logger.info(f"✓ API_KEY_PRIVATE_KEY: {'*' * 20}")
        logger.info(f"✓ LIGHTER_ACCOUNT_INDEX: {account_index}")
        logger.info(f"✓ LIGHTER_API_KEY_INDEX: {api_key_index}")

        # Load config
        logger.info("\n2. 加载配置...")
        config = get_config()
        logger.info("✓ 配置加载成功")

        # Initialize Lighter client
        logger.info("\n3. 初始化 Lighter 客户端...")
        lighter = LighterHedger(config)
        logger.info("✓ Lighter 客户端初始化成功")

        # Connect to Lighter
        logger.info("\n4. 连接到 Lighter...")
        connected = await lighter.connect()

        if not connected:
            logger.error("❌ 连接 Lighter 失败")
            return

        logger.info("✓ 成功连接到 Lighter")
        logger.info(f"  - Market ID: {lighter.market_id}")
        logger.info(f"  - Ticker: {lighter.ticker_symbol}")
        logger.info(f"  - Base Multiplier: {lighter.base_amount_multiplier}")
        logger.info(f"  - Price Multiplier: {lighter.price_multiplier}")

        # Test _fetch_positions (internal method)
        logger.info("\n5. 测试 _fetch_positions() 内部方法...")
        try:
            positions = await lighter._fetch_positions()
            logger.info(f"✓ _fetch_positions() 调用成功")
            logger.info(f"  - 返回的仓位数量: {len(positions)}")

            if positions:
                for i, pos in enumerate(positions):
                    logger.info(f"\n  仓位 #{i+1}:")
                    logger.info(f"    - Market ID: {pos.market_id}")
                    logger.info(f"    - Symbol: {pos.symbol}")
                    logger.info(f"    - Position: {pos.position}")
                    logger.info(f"    - Avg Price: {pos.avg_price if hasattr(pos, 'avg_price') else 'N/A'}")
            else:
                logger.info("  - 当前没有持仓")

        except Exception as e:
            logger.error(f"❌ _fetch_positions() 调用失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Test get_position (public method)
        logger.info("\n6. 测试 get_position() 公共方法...")
        try:
            position = await lighter.get_position()
            logger.info(f"✓ get_position() 调用成功")
            logger.info(f"  - 当前仓位: {position}")
            logger.info(f"  - 仓位类型: {'多头' if position > 0 else '空头' if position < 0 else '无仓位'}")

        except Exception as e:
            logger.error(f"❌ get_position() 调用失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Test get_balance
        logger.info("\n7. 测试 get_balance() 方法...")
        try:
            balance = await lighter.get_balance()
            logger.info(f"✓ get_balance() 调用成功")
            logger.info(f"  - 总余额: {balance.get('balance', 0)}")
            logger.info(f"  - 可用余额: {balance.get('available', 0)}")

        except Exception as e:
            logger.error(f"❌ get_balance() 调用失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Disconnect
        logger.info("\n8. 断开连接...")
        await lighter.disconnect()
        logger.info("✓ 已断开连接")

        logger.info("\n" + "=" * 60)
        logger.info("测试完成!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(test_lighter_positions())
