"""
仓位平衡检查和手动对冲工具
Check position balance and manually hedge if needed
"""
import asyncio
import logging
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def check_and_hedge():
    """检查仓位并进行手动对冲"""
    try:
        from config_loader import get_config
        from standx_client import StandXMarketMaker
        from lighter_client import LighterHedger

        logger.info("=" * 60)
        logger.info("仓位平衡检查工具")
        logger.info("=" * 60)

        # 加载配置
        config = get_config()

        # 初始化客户端
        logger.info("\n1. 初始化交易所客户端...")
        standx = StandXMarketMaker(config)
        lighter = LighterHedger(config)

        # 连接到 StandX
        logger.info("\n2. 连接到 StandX...")
        if not await standx.connect():
            logger.error("❌ 无法连接到 StandX")
            return

        logger.info("✓ 已连接到 StandX")

        # 连接到 Lighter
        logger.info("\n3. 连接到 Lighter...")
        if not await lighter.connect():
            logger.error("❌ 无法连接到 Lighter")
            return

        logger.info("✓ 已连接到 Lighter")

        # 获取仓位
        logger.info("\n4. 查询当前仓位...")
        standx_pos = await standx.get_position()
        lighter_pos = await lighter.get_position()

        logger.info(f"StandX 仓位: {standx_pos}")
        logger.info(f"Lighter 仓位: {lighter_pos}")

        # 计算仓位差异
        position_diff = standx_pos + lighter_pos
        logger.info(f"净仓位差异: {position_diff}")

        # 检查是否需要对冲
        if abs(position_diff) < Decimal('0.0001'):
            logger.info("\n✓ 仓位已平衡，无需对冲")
        else:
            logger.warning(f"\n⚠️  检测到仓位不平衡: {position_diff}")

            # 确定对冲方向和数量
            if position_diff > 0:
                # StandX 有多头敞口，需要在 Lighter 卖出
                hedge_side = "sell"
                hedge_qty = abs(position_diff)
            else:
                # StandX 有空头敞口，需要在 Lighter 买入
                hedge_side = "buy"
                hedge_qty = abs(position_diff)

            logger.info(f"需要对冲: {hedge_side} {hedge_qty} on Lighter")

            # 询问用户确认
            print(f"\n是否执行对冲操作? ({hedge_side} {hedge_qty} on Lighter)")
            user_input = input("输入 'yes' 确认: ").strip().lower()

            if user_input == 'yes':
                logger.info("\n5. 执行对冲操作...")

                # 执行对冲
                success = await lighter.place_hedge_order(
                    side=hedge_side,
                    quantity=hedge_qty,
                    price=None  # 使用市价
                )

                if success:
                    logger.info("✓ 对冲订单已成功下达")

                    # 等待几秒钟让订单成交
                    await asyncio.sleep(3)

                    # 重新检查仓位
                    logger.info("\n6. 验证对冲结果...")
                    standx_pos_after = await standx.get_position()
                    lighter_pos_after = await lighter.get_position()
                    position_diff_after = standx_pos_after + lighter_pos_after

                    logger.info(f"对冲后 StandX 仓位: {standx_pos_after}")
                    logger.info(f"对冲后 Lighter 仓位: {lighter_pos_after}")
                    logger.info(f"对冲后净仓位差异: {position_diff_after}")

                    if abs(position_diff_after) < Decimal('0.0001'):
                        logger.info("\n✓ 仓位已成功平衡!")
                    else:
                        logger.warning(f"\n⚠️  仓位仍有差异: {position_diff_after}")
                else:
                    logger.error("❌ 对冲订单失败")
            else:
                logger.info("取消对冲操作")

        # 获取余额信息
        logger.info("\n7. 查询账户余额...")
        lighter_balance = await lighter.get_balance()
        logger.info(f"Lighter 可用余额: {lighter_balance['available']} USDC")

        # 断开连接
        logger.info("\n8. 断开连接...")
        await standx.disconnect()
        await lighter.disconnect()

        logger.info("\n" + "=" * 60)
        logger.info("检查完成")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"\n❌ 发生错误: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(check_and_hedge())
