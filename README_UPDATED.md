# StandX Maker Hedger - 做市对冲系统
## 概述

这是一个自动化做市+对冲系统，在 StandX 上做市，并在 Lighter 上对冲风险。

## 邀请链接，没有注册StandX的可以使用这个链接来注册新账户

#### StandX： [https://standx.com/referral?code=JAAWW] https://standx.com/referral?code=JAAWW


### 核心策略

1. **StandX 做市**: 在当前价格 ±10% 范围内持续挂买卖限价单
2. **价格监控**: 当价格变动接近订单价格时自动撤单
3. **自动对冲**: 如果订单成交，立即在 Lighter 上挂反向订单对冲
4. **风险控制**: 多重安全机制保护资金

## 特点

✅ **WebSocket 实时** - 实时订单更新和成交通知
✅ **官方 Lighter SDK** - 使用 Lighter 官方 Python SDK
✅ **异步架构** - 全异步 I/O，高性能
✅ **开箱即用** - 仅需配置 .env 即可运行

## 项目结构

```
standx_maker_hedger/
├── config.json              # 策略配置文件
├── .env.example             # 环境变量模板
├── config_loader.py         # 配置加载器
├── main.py                  # 主程序入口
├── standx_client.py         # StandX 客户端 (基于真实项目)
├── lighter_client.py        # Lighter 客户端 (基于真实项目)
├── risk_manager.py          # 风险管理模块
├── requirements.txt         # Python依赖
├── setup.sh                 # 一键安装脚本
├── start.sh                 # 启动脚本
├── activate.sh              # 快速激活虚拟环境
├── venv/                    # 独立虚拟环境
└── logs/                    # 日志目录
```

## 快速开始

### 1. 安装依赖

```bash
cd standx_maker_hedger

# 一键安装脚本
./setup.sh

# 或者手动创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入你的凭证
nano .env
```

**必需的环境变量：**

```bash
# StandX (Solana 钱包私钥，Base58 格式)
SOLANA_PRIVATE_KEY=你的Solana私钥

# Lighter (API Key 私钥)
API_KEY_PRIVATE_KEY=你的Lighter_API_Key私钥
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=0
```

### 3. 修改策略配置

编辑 [config.json](config.json):

```json
{
  "trading": {
    "symbol": "BTC-USD",           // 交易对 (StandX 格式)
    "spread_percentage": 0.1,      // 10% 价差
    "order_size": "0.01",          // 订单大小
    "check_interval_seconds": 5    // 检查间隔
  },
  "exchanges": {
    "standx": {
      "auth_url": "https://api.standx.com",
      "trade_url": "https://perps.standx.com",
      "chain": "solana"
    },
    "lighter": {
      "enabled": true              // 启用 Lighter 对冲
    }
  }
}
```

### 4. 启动机器人

```bash
# 方式1: 使用启动脚本 (推荐)
chmod +x start.sh
./start.sh

# 方式2: 直接运行
python main.py
```

### 5. 停止机器人

按 `Ctrl+C` 停止，机器人会：
1. 取消所有 StandX 上的挂单
2. (可选)平仓 Lighter 上的持仓
3. 保存日志并退出

## 核心组件说明

### 1. StandX 客户端 ([standx_client.py](standx_client.py))

提供完整的 StandX 交易功能（solana）：

- **REST API 登录**: Solana 钱包签名认证
- **WebSocket 订单更新**: 实时接收订单成交通知
- **下单/撤单**: 限价单管理
- **持仓查询**: 实时持仓跟踪

**关键功能：**
```python
# 连接到 StandX
await standx.connect()

# 下单
order = await standx.place_order("buy", 50000.0, 0.01)

# 取消订单
await standx.cancel_orders([order_id])

# 获取持仓
position = await standx.get_position()
```

### 2. Lighter 客户端 ([lighter_client.py](lighter_client.py))

使用官方 SDK 提供 Lighter 交易功能：

- **Lighter SDK**: 使用官方 Python SDK
- **市场配置**: 自动获取市场参数
- **下单对冲**: 限价单/市价单
- **持仓查询**: 实时持仓跟踪

**关键功能：**
```python
# 连接到 Lighter
await lighter.connect()

# 对冲下单
success = await lighter.place_hedge_order("sell", 0.01, 50100.0)

# 获取持仓
position = await lighter.get_position()
```

### 3. 主控制器 ([main.py](main.py))

协调所有组件，实现完整套利逻辑：

1. **连接交易所**: 异步连接 StandX 和 Lighter
2. **挂单做市**: 在 StandX 上挂买卖单
3. **监控成交**: 通过 WebSocket 接收成交通知
4. **自动对冲**: 在 Lighter 上自动对冲
5. **风险控制**: 检查各项风险限制

## 工作流程

```
启动机器人
    ↓
连接 StandX (REST 登录 + WebSocket)
    ↓
连接 Lighter (SDK 初始化)
    ↓
获取当前市场价格 (例如: $50,000)
    ↓
计算挂单价格
  - Bid: $45,000 (当前价 -10%)
  - Ask: $55,000 (当前价 +10%)
    ↓
在 StandX 挂限价单
    ↓
持续监控价格变化
    ↓
如果价格变动超过 5%
  → 撤销所有订单
  → 在新价格重新挂单
    ↓
如果订单成交 (通过 WebSocket 通知)
  → 立即在 Lighter 挂反向单对冲
  → 更新持仓和 P&L
    ↓
检查风险限制
  - 持仓超限?
  - 每日亏损超限?
  - 触发紧急止损?
    ↓
重复循环
```

## 配置详解

### 交易配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| symbol | 交易对 (StandX 格式: BTC-USD) | BTC-USD |
| spread_percentage | 挂单价差百分比 | 0.1 (10%) |
| order_size | 单笔订单大小 | 0.01 |
| leverage | 杠杆倍数 | 1 |
| margin_mode | 保证金模式 | cross |
| check_interval_seconds | 检查间隔(秒) | 5 |

### 风险管理

| 参数 | 说明 | 默认值 |
|------|------|--------|
| max_position_size | 最大持仓(USD) | 1000.0 |
| max_daily_loss | 每日最大亏损 | 500.0 |
| min_profit_threshold | 最小利润阈值 | 5.0 |
| emergency_stop_loss | 紧急止损 | 1000.0 |
| max_open_orders | 最大挂单数 | 10 |

### 策略配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| hedge_immediately | 立即对冲 | true |
| cancel_distance_percentage | 撤单距离百分比 | 0.05 (5%) |
| close_position_on_shutdown | 关闭时平仓 | false |

## 日志监控

### 日志文件位置

`logs/standx_maker_hedger.log`

### 日志内容

- ✅ 连接状态
- 📊 订单操作 (下单/撤单/成交)
- 💱 对冲执行情况
- ⚠️ 风险事件
- ❌ 错误信息

### 实时状态输出

每 60 秒输出一次:
```
============================================================
Bot Status at 2024-01-11 10:30:00
  Current Price: 50000.0
  Open Orders (StandX): 2
  StandX Position: 0.0
  Lighter Position: 0.0
  Daily P&L: $10.50
  Total P&L: $125.30
  Trade Count: 8
  Emergency Stop: False
============================================================
```

## 依赖说明

核心依赖：
- `python-dotenv` - 环境变量管理
- `websockets` - WebSocket 连接
- `base58` - Solana 地址编码
- `solders` - Solana 钱包操作
- `cryptography` - Ed25519 签名
- `lighter` - Lighter 官方 SDK

完整依赖列表见 [requirements.txt](requirements.txt)

## 常见问题

### Q: 如何获取 Lighter 的 API_KEY_PRIVATE_KEY?

A: 参考 Lighter 官方文档创建 API Key。这是 Lighter 平台提供的 API 私钥字符串。

### Q: Solana 私钥格式是什么?

A: Base58 编码的私钥，通常从 Phantom/Solflare 等钱包导出。

### Q: 对冲失败怎么办?

A: 机器人会：
1. 立即触发紧急停止
2. 记录详细错误日志
3. 停止所有新操作

你需要手动在 Lighter 上对冲，然后检查日志找出失败原因。

### Q: 如何测试系统?

A: 建议步骤：
1. 先用很小的订单量测试 (如 0.001)
2. 设置低的风险限制
3. 在测试网测试 (如果可用)
4. 监控日志确保一切正常
5. 逐步增加订单量

### Q: WebSocket 断线怎么办?

A: StandX WebSocket 管理器包含自动重连机制，断线后会在 5 秒后自动重连。

## 安全建议

1. ⚠️ **测试环境优先**: 先在测试网充分测试
2. 💰 **小额启动**: 用最小订单量测试策略
3. 📊 **持续监控**: 定期检查日志和持仓
4. 🔐 **保护私钥**: 确保 .env 文件安全，不要提交到 git
5. 🚨 **设置告警**: 配置风险限制和紧急止损

## 紧急处理

### 对冲失败

机器人会自动停止，你需要：
1. 检查 `logs/arbitrage_bot.log` 了解失败原因
2. 手动在 Lighter 上对冲未对冲的持仓
3. 修复问题后重启

### 达到亏损限制

机器人会自动停止交易并取消所有挂单：
1. 检查亏损原因
2. 评估策略参数
3. 决定是否继续

### 网络问题

- StandX WebSocket 会自动重连
- REST API 调用会重试
- 如果持续失败，机器人会记录错误并继续尝试

## 后续版本计划∂

可以考虑添加：

- [ ] Telegram 通知机器人
- [ ] 多层挂单策略
- [ ] 性能指标统计 (Sharpe ratio 等)
- [ ] 数据库存储历史交易
- [ ] 多交易对支持

## 技术支持

- **StandX API 文档**: https://docs.standx.com
- **Lighter SDK**: https://github.com/elliottech/lighter-python

- **问题反馈**: 检查日志文件或联系开发者

## 鸣谢，以下大佬的项目给了启发和帮助
https://github.com/your-quantguy
https://github.com/Dazmon88

---

**免责声明**: 加密货币交易有风险，本系统不保证盈利。请谨慎使用，风险自负。
