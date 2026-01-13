"""
🔧 关键修复: Lighter 对冲未执行问题

## 问题诊断

从日志分析发现:
1. ✅ 订单在 StandX 上成交了
2. ❌ 但没有触发 Lighter 对冲
3. ❌ 日志中没有 "✓ FILLED" 消息
4. ❌ 日志中没有 "Detected StandX fill" 消息
5. ❌ 日志中没有 "Hedging on Lighter" 消息

结论: WebSocket 订单更新回调根本没有被触发

## 根本原因

**异步函数调用错误** ⚠️

在 standx_client.py 的 `_on_ws_order_update` 方法中:

```python
# 错误的调用方式 (之前的代码)
if self._order_update_handler:
    self._order_update_handler({  # ❌ 同步调用异步函数
        "order_id": order_id,
        "side": side,
        "price": price,
        "qty": filled_qty,
        "status": "filled"
    })
```

问题:
- `handle_standx_order_fill` 是一个 **async 函数**
- 但是在 `_on_ws_order_update` 中**直接调用**了它
- 这是**同步调用异步函数** - 函数不会真正执行！
- Python 会创建一个 coroutine 对象但不会 await 它
- 结果: 对冲逻辑永远不会运行

## 修复方案

使用 `asyncio.create_task()` 正确调度异步回调:

```python
# 正确的调用方式 (修复后的代码)
if self._order_update_handler:
    logger.info(f"Triggering hedge callback for order {order_id}")
    # Schedule async callback properly
    import asyncio
    asyncio.create_task(self._order_update_handler({  # ✅ 异步调度
        "order_id": order_id,
        "side": side,
        "price": price,
        "qty": filled_qty,
        "status": "filled"
    }))
```

## 其他改进

### 1. 添加调试日志
```python
# 记录原始 WebSocket 消息
logger.debug(f"[WS] Raw order update: {order_data}")

# 记录解析后的字段
logger.debug(f"[WS] Parsed: id={order_id}, status={status}, ...")

# 记录回调触发
logger.info(f"Triggering hedge callback for order {order_id}")

# 检测未注册的 handler
logger.warning("No order update handler registered!")

# 记录订单不在 active_orders 的情况
logger.debug(f"[WS] Order {order_id} not in active_orders (status={status})")
```

### 2. 改进错误处理
```python
except Exception as e:
    logger.error(f"Error processing order update: {e}", exc_info=True)
    # 添加 exc_info=True 以显示完整堆栈跟踪
```

## 测试验证

修复后，应该看到以下日志序列:

```
[260113 10:00:00.00]INFO[standx_client.py:329] ✓ FILLED: BUY 0.01 BTC-USD @ $91,200.00 ($912.00)
[260113 10:00:00.01]INFO[standx_client.py:331] Triggering hedge callback for order 12345
[260113 10:00:00.02]INFO[main.py:76] Detected StandX fill: buy 0.01@91200.0
[260113 10:00:00.03]INFO[main.py:87] Hedging on Lighter: sell 0.01
[260113 10:00:00.50]INFO[lighter_client.py:223] → Hedging on Lighter: SELL 0.01 BTC @ $91,200.00 ($912.00)
[260113 10:00:00.75]INFO[lighter_client.py:232] ✓ Hedge placed successfully
[260113 10:00:00.76]INFO[main.py:98] Hedge placed successfully
```

## 启用调试日志 (如需要)

在 config.json 中临时启用:
```json
{
  "logging": {
    "log_level": "DEBUG",
    "log_file": "logs/arbitrage_bot.log"
  }
}
```

这将显示所有 DEBUG 级别的日志，帮助诊断任何剩余问题。

## 预期结果

修复后:
✅ 订单成交时会立即触发对冲
✅ Lighter 上会自动下对冲订单
✅ 仓位保持平衡: SX + LT ≈ 0
✅ 日志中会显示完整的成交和对冲流程

## 重要提示

⚠️ **必须重启机器人** 才能应用此修复!

```bash
# 停止当前运行的机器人 (Ctrl+C)
# 然后重新启动
python main.py
```
"""