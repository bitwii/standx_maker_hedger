# WebSocket订阅格式修复

## 问题发现

从日志 `log_26011316/arbitrage_bot.log` 第268行发现致命错误：

```
[260113 14:57:33.53] [WS] RAW ORDER MESSAGE: {'code': 400, 'message': 'invalid request payload: {"method": "subscribe", "params": ["order"]}'}
```

**根本原因：WebSocket订阅格式错误，导致StandX拒绝订阅请求**

## 问题分析

### 错误的格式（修复前）

```python
# 分两次发送
# 第一次：认证
{
    "method": "auth",
    "params": {"token": "..."}
}

# 第二次：订阅
{
    "method": "subscribe",
    "params": ["order"]
}
```

**结果：** StandX返回 `400 invalid request payload`

### 正确的格式（修复后）

参考 [cross-exchange-arbitrage/exchanges/standx.py](../cross-exchange-arbitrage/exchanges/standx.py) 的工作代码：

```python
# 一次发送，认证和订阅合并
{
    "auth": {
        "token": "...",
        "streams": [
            {"channel": "order"}
        ]
    }
}
```

## 修复内容

### 1. 修复认证和订阅逻辑 (standx_client.py:92-106)

**修复前：**
```python
async def _authenticate_and_subscribe(self):
    auth_msg = {"method": "auth", "params": {"token": self.token}}
    await self._ws.send(json.dumps(auth_msg))

    subscribe_msg = {"method": "subscribe", "params": ["order"]}
    await self._ws.send(json.dumps(subscribe_msg))
```

**修复后：**
```python
async def _authenticate_and_subscribe(self):
    auth_payload = {
        "auth": {
            "token": self.token,
            "streams": [
                {"channel": "order"}
            ]
        }
    }
    await self._ws.send(json.dumps(auth_payload))
```

### 2. 修复消息处理逻辑 (standx_client.py:108-138)

**关键变化：**

1. **认证响应处理：**
   ```python
   if msg.get("channel") == "auth":
       auth_data = msg.get("data", {})
       if auth_data.get("code") == 0:  # StandX用code=0表示成功
           self.logger.info("[WS] Authentication successful")
   ```

2. **订单消息格式：**
   ```python
   # 修复前：msg.get("type") == "order"
   # 修复后：msg.get("channel") == "order"

   if msg.get("channel") == "order":
       order_data = msg.get("data", {})
       self.on_message_callback(order_data)
   ```

## 影响链

**WebSocket订阅失败**
  ↓
**收不到任何订单更新消息**
  ↓
**`_on_ws_order_update` 回调从未被调用**
  ↓
**`handle_standx_order_fill` 从未被触发**
  ↓
**Lighter对冲从未执行**
  ↓
**仓位不平衡（SX=0.02BTC, LT=0.00BTC）**

## 预期效果

修复后重启机器人，应该看到：

```
[260113 XX:XX:XX.XX]INFO[standx_client.py:106] [WS] Sent auth & subscription
[260113 XX:XX:XX.XX]INFO[standx_client.py:121] [WS] Authentication successful
```

当订单成交时：
```
[260113 XX:XX:XX.XX]INFO[standx_client.py:115] [WS] RAW ORDER MESSAGE: {'channel': 'order', 'data': {...}}
[260113 XX:XX:XX.XX]INFO[standx_client.py:310] [WS] ORDER UPDATE CALLBACK: {...}
[260113 XX:XX:XX.XX]INFO[standx_client.py:323] [WS] PARSED: id=XXX, status=filled, ...
[260113 XX:XX:XX.XX]INFO[standx_client.py:334] ✓ FILLED: BUY 0.01 BTC-USD @ $92,000.00
[260113 XX:XX:XX.XX]INFO[standx_client.py:336] Triggering hedge callback for order XXX
[260113 XX:XX:XX.XX]INFO[main.py:76] Detected StandX fill: buy 0.01@92000.0
[260113 XX:XX:XX.XX]INFO[main.py:87] Hedging on Lighter: sell 0.01
[260113 XX:XX:XX.XX]INFO[lighter_client.py:223] → Hedging on Lighter: SELL 0.01 BTC @ $92,000.00
[260113 XX:XX:XX.XX]INFO[lighter_client.py:232] ✓ Hedge placed successfully
```

## 测试步骤

1. **重启机器人**
   ```bash
   Ctrl+C  # 停止当前机器人
   python main.py
   ```

2. **检查认证日志**
   - 应该看到 `[WS] Authentication successful`
   - 不应该看到 `400 invalid request payload` 错误

3. **等待订单成交**
   - 应该看到 `[WS] RAW ORDER MESSAGE`
   - 应该看到对冲日志链

4. **验证仓位平衡**
   - Status日志中 `SX + LT ≈ 0`

## 参考

- 工作代码：[cross-exchange-arbitrage/exchanges/standx.py:104-149](../cross-exchange-arbitrage/exchanges/standx.py#L104-L149)
- StandX WebSocket文档格式：认证和订阅合并为单次请求
- 消息格式：`{"channel": "...", "data": {...}}`
