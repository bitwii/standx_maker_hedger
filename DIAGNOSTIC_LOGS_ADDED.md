# 诊断日志已添加

## 问题回顾

从日志 `log_26011313/arbitrage_bot.log` 看到：
- ✅ 订单在StandX成交了（仓位变化：0 → 0.01BTC → -0.01BTC）
- ❌ 完全没有对冲日志
- ❌ 没有 "✓ FILLED" 日志
- ❌ 没有任何WebSocket消息日志

**推测原因：WebSocket消息格式不匹配或回调未被触发**

## 已添加的诊断日志

### 1. WebSocket消息接收层 (standx_client.py:116-117)
```python
# 记录所有收到的订单相关消息
if msg.get("type") == "order" or "order" in msg_str.lower():
    self.logger.info(f"[WS] RAW ORDER MESSAGE: {msg}")
```

**作用：查看StandX WebSocket发送的原始消息格式**

### 2. 订单更新回调层 (standx_client.py:310)
```python
# 记录传递给回调的数据
logger.info(f"[WS] ORDER UPDATE CALLBACK: {order_data}")
```

**作用：确认回调函数是否被调用**

### 3. 订单解析层 (standx_client.py:323)
```python
# 记录解析后的字段
logger.info(f"[WS] PARSED: id={order_id}, status={status}, side={side}, qty={qty}, filled={filled_qty}")
```

**作用：检查字段解析是否正确**

### 4. active_orders检查层 (standx_client.py:327 & 355)
```python
# 订单在active_orders中
logger.info(f"[WS] Order {order_id} found in active_orders")

# 订单不在active_orders中
logger.info(f"[WS] Order {order_id} NOT in active_orders (status={status}). Active orders: {list(self.active_orders.keys())}")
```

**作用：检查订单是否在追踪列表中**

## 重启机器人

```bash
# 停止当前运行的机器人
Ctrl+C

# 重新启动
python main.py
```

## 预期日志输出

### 场景1：收到订单消息但格式不匹配
```
[260113 14:00:00.00]INFO[standx_client.py:117] [WS] RAW ORDER MESSAGE: {...}
# 如果没有后续日志，说明 msg.get("type") != "order"
```

### 场景2：收到订单消息且格式匹配
```
[260113 14:00:00.00]INFO[standx_client.py:117] [WS] RAW ORDER MESSAGE: {...}
[260113 14:00:00.01]INFO[standx_client.py:310] [WS] ORDER UPDATE CALLBACK: {...}
[260113 14:00:00.02]INFO[standx_client.py:323] [WS] PARSED: id=XXX, status=YYY, ...
```

### 场景3：订单不在active_orders中
```
[260113 14:00:00.00]INFO[standx_client.py:117] [WS] RAW ORDER MESSAGE: {...}
[260113 14:00:00.01]INFO[standx_client.py:310] [WS] ORDER UPDATE CALLBACK: {...}
[260113 14:00:00.02]INFO[standx_client.py:323] [WS] PARSED: id=XXX, status=filled, ...
[260113 14:00:00.03]INFO[standx_client.py:355] [WS] Order XXX NOT in active_orders (status=filled). Active orders: [...]
```

### 场景4：一切正常（理想情况）
```
[260113 14:00:00.00]INFO[standx_client.py:117] [WS] RAW ORDER MESSAGE: {...}
[260113 14:00:00.01]INFO[standx_client.py:310] [WS] ORDER UPDATE CALLBACK: {...}
[260113 14:00:00.02]INFO[standx_client.py:323] [WS] PARSED: id=XXX, status=filled, ...
[260113 14:00:00.03]INFO[standx_client.py:327] [WS] Order XXX found in active_orders
[260113 14:00:00.04]INFO[standx_client.py:334] ✓ FILLED: BUY 0.01 BTC-USD @ $91,200.00 ($912.00)
[260113 14:00:00.05]INFO[standx_client.py:336] Triggering hedge callback for order XXX
[260113 14:00:00.06]INFO[main.py:76] Detected StandX fill: buy 0.01@91200.0
[260113 14:00:00.07]INFO[main.py:87] Hedging on Lighter: sell 0.01
[260113 14:00:00.50]INFO[lighter_client.py:223] → Hedging on Lighter: SELL 0.01 BTC @ $91,200.00
[260113 14:00:00.75]INFO[lighter_client.py:232] ✓ Hedge placed successfully
```

## 下一步

1. **重启机器人**
2. **等待订单成交**
3. **把新的日志文件发给我**
4. 我会根据日志：
   - 确定WebSocket消息的实际格式
   - 找出为什么回调没有触发
   - 修复问题并确保对冲正常执行

## 注意事项

这些诊断日志会产生较多输出，但这是必要的。一旦问题修复，我们会移除这些临时诊断日志，恢复到正常日志级别。
