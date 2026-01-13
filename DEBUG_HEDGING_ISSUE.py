"""
临时调试配置 - 用于诊断对冲问题
"""

# 在 config.json 中临时修改日志级别：
"""
{
  "logging": {
    "log_level": "DEBUG",  // 从 INFO 改为 DEBUG
    "log_file": "logs/arbitrage_bot.log"
  },
  ...
}
"""

# 或者直接在代码中临时启用调试
"""
import logging
logging.getLogger('standx_client').setLevel(logging.DEBUG)
logging.getLogger('main').setLevel(logging.DEBUG)
"""

# 调试后需要查看的关键日志：
"""
1. [WS] Raw order update: {...}
   - 查看实际收到的 WebSocket 消息格式

2. [WS] Parsed: id=XXX, status=YYY, ...
   - 查看解析后的字段值

3. [WS] Order XXX not in active_orders
   - 如果订单不在 active_orders 中，说明时序问题

4. Triggering hedge callback for order XXX
   - 如果看到这个，说明回调被触发了

5. Detected StandX fill: ...
   - 如果看到这个，说明 handle_standx_order_fill 被调用了
"""

# 可能的问题和解决方案：
"""
问题1: WebSocket 消息格式不匹配
  - status 字段可能是大写 "FILLED" 而不是小写 "filled"
  - 字段名可能不是 "filled_qty" 而是其他名称

问题2: 订单成交时不在 active_orders 中
  - 订单可能在撤单后才收到成交消息
  - 需要检查订单添加到 active_orders 的时机

问题3: handler 未注册
  - setup_order_update_handler 可能没有被调用
  - 或者在 WebSocket 连接建立前就注册了

问题4: 异步调用问题
  - handle_standx_order_fill 是 async 函数
  - _order_update_handler 调用时需要 await
"""
