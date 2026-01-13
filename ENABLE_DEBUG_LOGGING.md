# 启用调试日志来诊断对冲问题

## 问题分析

从日志看到：
- ✅ 订单在StandX成交了（仓位变化：0 → 0.01BTC → -0.01BTC）
- ❌ 完全没有对冲日志
- ❌ 没有 "✓ FILLED" 日志
- ❌ 没有任何WebSocket DEBUG消息

**原因：可能是WebSocket消息格式不匹配，需要查看原始消息**

## 解决方案：启用DEBUG日志

### 方法1：修改config.json（推荐）

编辑 `config.json`，把日志级别改为DEBUG：

```json
{
  "logging": {
    "log_level": "DEBUG",
    "log_file": "logs/arbitrage_bot.log"
  },
  ...
}
```

### 方法2：临时修改代码

在 `standx_client.py` 第110行 `_handle_message` 方法中，添加一行强制日志：

```python
def _handle_message(self, msg_str: str):
    """Handle WebSocket message"""
    try:
        msg = json.loads(msg_str)

        # 🔥 添加这一行：强制打印所有消息
        self.logger.info(f"[WS] RAW MESSAGE: {msg}")

        # Handle different message types
        if msg.get("type") == "order":
            ...
```

## 启用DEBUG后应该看到什么

重启机器人后，你应该看到：

```
[260113 14:00:00.00]DEBUG[standx_client.py:113] [WS] RAW MESSAGE: {...}
[260113 14:00:00.01]DEBUG[standx_client.py:306] [WS] Raw order update: {...}
[260113 14:00:00.02]DEBUG[standx_client.py:319] [WS] Parsed: id=XXX, status=YYY, ...
```

## 重启机器人

```bash
# 停止当前运行的机器人
Ctrl+C

# 重新启动
python main.py
```

## 下一步

等订单成交后，把新的日志文件发给我，我会：
1. 查看实际的WebSocket消息格式
2. 修复消息解析逻辑
3. 确保对冲正常执行
