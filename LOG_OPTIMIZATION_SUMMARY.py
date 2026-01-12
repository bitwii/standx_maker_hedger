"""
日志优化效果对比
"""

# ============================================================
# 优化前 - 每60秒打印一次，即使没有变化
# ============================================================
"""
[10:15:46] INFO  [main.py:257] ============================================================
[10:15:46] INFO  [main.py:258] Bot Status at 2026-01-12 10:15:46
[10:15:46] INFO  [main.py:259]   Current Price: 90690
[10:15:46] INFO  [main.py:260]   Open Orders (StandX): 2
[10:15:46] INFO  [main.py:261]   StandX Position: 0
[10:15:46] INFO  [main.py:262]   Lighter Position: 0.00000
[10:15:46] INFO  [main.py:263]   Daily P&L: $0.00
[10:15:46] INFO  [main.py:264]   Total P&L: $0.00
[10:15:46] INFO  [main.py:265]   Trade Count: 0
[10:15:46] INFO  [main.py:266]   Emergency Stop: False
[10:15:46] INFO  [main.py:267] ============================================================
[10:16:48] INFO  [main.py:257] ============================================================
[10:16:48] INFO  [main.py:258] Bot Status at 2026-01-12 10:16:48
[10:16:48] INFO  [main.py:259]   Current Price: 90673.31
[10:16:48] INFO  [main.py:260]   Open Orders (StandX): 2
[10:16:48] INFO  [main.py:261]   StandX Position: 0
[10:16:48] INFO  [main.py:262]   Lighter Position: 0.00000
[10:16:48] INFO  [main.py:263]   Daily P&L: $0.00
[10:16:48] INFO  [main.py:264]   Total P&L: $0.00
[10:16:48] INFO  [main.py:265]   Trade Count: 0
[10:16:48] INFO  [main.py:266]   Emergency Stop: False
[10:16:48] INFO  [main.py:267] ============================================================

问题:
- 每次10行日志
- 即使没有变化也打印
- 占用大量日志空间
"""

# ============================================================
# 优化后 - 只在有变化或每小时打印一次
# ============================================================
"""
[10:15:46] INFO  [main.py:120] Order placed: BUY 0.001 BTC-USD @ $90690
[10:15:46] INFO  [main.py:120] Order placed: SELL 0.001 BTC-USD @ $90850
[10:15:46] INFO  [main.py:289] Status: Price=$90,690.00 | Orders=2 | Pos: StandX=0 Lighter=0.00000 | P&L=$0.00 | Trades=0

# ... 如果没有变化，不会打印状态日志 ...
# ... 1小时后自动打印一次 ...

[11:15:46] INFO  [main.py:289] Status: Price=$91,234.50 | Orders=2 | Pos: StandX=0 Lighter=0.00000 | P&L=$0.00 | Trades=0

# 当有订单成交时:
[11:20:15] INFO  [standx_client.py:323] ✓ FILLED: BUY 0.001 BTC-USD @ $91,200.00 ($91.20)
[11:20:15] INFO  [lighter_client.py:223] → Hedging on Lighter: SELL 0.001 BTC @ $91,200.00 ($91.20)
[11:20:16] INFO  [lighter_client.py:232] ✓ Hedge placed successfully
[11:20:16] INFO  [main.py:289] Status: Price=$91,234.50 | Orders=1 | Pos: StandX=0.001 Lighter=-0.001 | P&L=$0.00 | Trades=1

优点:
- 单行显示，简洁明了
- 只在有事件发生时打印
- 每小时自动打印一次作为"心跳"
- 大大减少日志量
"""

# ============================================================
# 触发状态日志的条件
# ============================================================
"""
状态日志会在以下情况打印:

1. 仓位变化 (StandX 或 Lighter)
2. 订单数量变化 (下单、成交、撤单)
3. 有新交易成交
4. P&L 变化 (超过 $0.01)
5. 距离上次打印已过 1 小时

日志格式:
Status: Price=$XX,XXX.XX | Orders=N | Pos: StandX=X Lighter=X | P&L=$X.XX | Trades=N
"""
