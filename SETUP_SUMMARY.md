# StandX Maker Hedger - 设置完成

## 🎉 项目完成

**StandX Maker Hedger** 是一个自动化做市+对冲系统。

## 📁 项目文件

### 核心模块
1. **[standx_client.py](standx_client.py)**
   - StandX 客户端实现
   - WebSocket 订单更新
   - Solana 钱包签名认证
   - 异步下单/撤单/查询

2. **[lighter_client.py](lighter_client.py)**
   - Lighter 客户端实现
   - 使用官方 Lighter Python SDK
   - 市场配置自动获取
   - 异步对冲交易

3. **[standx_protocol/](standx_protocol/)**
   - `perps_auth.py` - StandX 认证模块
   - `perp_http.py` - StandX HTTP 客户端

4. **[main.py](main.py)**
   - 异步主程序入口
   - 协调 StandX 和 Lighter
   - 实现完整做市+对冲逻辑

### 配置文件
4. **[.env.example](.env.example)** - 更新
   - 添加 Lighter 必需的环境变量
   - `API_KEY_PRIVATE_KEY`
   - `LIGHTER_ACCOUNT_INDEX`
   - `LIGHTER_API_KEY_INDEX`

5. **[requirements.txt](requirements.txt)** - 更新
   - 添加 `websockets`
   - 添加 `asyncio`
   - 添加 Lighter SDK (from GitHub)

6. **[start.sh](start.sh)** - 更新
   - 支持多个虚拟环境路径
   - 运行 `main.py` 而不是 `arbitrage_bot.py`

### 文档
7. **[README_UPDATED.md](README_UPDATED.md)** ⭐ NEW
   - 完整的使用文档
   - 基于真实项目的说明
   - 详细的配置说明

8. **[setup.sh](setup.sh)** ⭐ NEW
   - 一键安装脚本
   - 自动配置虚拟环境
   - 安装所有依赖

## 🚀 快速开始

### 方法 1: 使用 setup 脚本 (推荐)

```bash
cd standx_maker_hedger

# 一键安装
./setup.sh

# 编辑配置
nano .env

# 启动
./start.sh
```

### 方法 2: 手动安装

```bash
cd standx_maker_hedger

# 创建独立虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置
cp .env.example .env
nano .env

# 运行
python main.py
```

## ⚙️ 必需配置

### .env 文件

```bash
# StandX (Solana 钱包私钥 - Base58 格式)
SOLANA_PRIVATE_KEY=你的Base58格式Solana私钥

# Lighter (API Key 私钥)
API_KEY_PRIVATE_KEY=你的Lighter_API私钥
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=0
```

### config.json (可选调整)

主要参数:
- `trading.symbol`: 交易对 (如 "BTC-USD")
- `trading.spread_percentage`: 价差 (默认 0.1 = 10%)
- `trading.order_size`: 订单大小 (默认 "0.01")
- `risk_management.max_position_size`: 最大持仓
- `risk_management.max_daily_loss`: 每日最大亏损

## 🔧 核心特性

### 1. StandX 集成
- ✅ WebSocket 连接 (wss://perps.standx.com/ws-stream/v1)
- ✅ 实时订单更新通知
- ✅ Solana 签名认证
- ✅ 异步 API 调用

### 2. Lighter 集成
- ✅ 官方 Lighter Python SDK
- ✅ 自动获取市场配置
- ✅ 异步订单提交
- ✅ 持仓查询和余额查询

### 3. 架构特性
- ✅ 全异步 I/O (asyncio)
- ✅ WebSocket 自动重连
- ✅ 模块化设计
- ✅ 完善的错误处理

## 📊 工作流程

```
程序启动
    ↓
加载配置 (config.json + .env)
    ↓
连接 StandX
  - REST API 登录 (Solana 签名)
  - 启动 WebSocket (订单更新)
    ↓
连接 Lighter
  - 初始化 SDK
  - 获取市场配置
    ↓
获取当前价格 → 计算挂单价格
    ↓
在 StandX 挂买卖单
    ↓
【主循环】
  1. 检查价格变化
  2. 如果价格变动 > 5% → 撤单重挂
  3. WebSocket 监听订单成交
  4. 成交时 → 立即在 Lighter 对冲
  5. 更新风险管理数据
  6. 检查风险限制
  7. 每 60 秒打印状态
    ↓
用户按 Ctrl+C 停止
    ↓
取消所有订单 → 断开连接 → 退出
```

## 🎯 与旧版本对比

| 特性 | 旧版本 | 新版本 |
|------|--------|--------|
| StandX 客户端 | 简化版 | 真实项目代码 |
| Lighter 客户端 | 模板 | 真实项目代码 + SDK |
| 架构 | 同步 | 异步 (asyncio) |
| WebSocket | 无 | 有 (实时订单更新) |
| 订单监控 | 轮询 | 实时推送 |
| 对冲速度 | 较慢 | 快速 (异步) |
| 代码来源 | 新写 | 验证过的生产代码 |

## ⚠️ 重要注意事项

### 1. 环境变量格式
- **SOLANA_PRIVATE_KEY**: Base58 编码 (Phantom/Solflare 导出格式)
- **API_KEY_PRIVATE_KEY**: Lighter API Key 私钥字符串

### 2. 依赖安装
Lighter SDK 从 GitHub 安装:
```bash
pip install git+https://github.com/elliottech/lighter-python.git
```

### 3. 测试建议
- 从很小的订单量开始 (如 0.001)
- 设置低的风险限制
- 密切监控日志文件
- 确认对冲正常工作后再增加规模

### 4. 日志位置
- 文件: `logs/standx_maker_hedger.log`
- 同时输出到控制台
- 每 60 秒输出状态摘要

## 🐛 故障排查

### 问题: "Lighter SDK not available"
**解决**:
```bash
pip install git+https://github.com/elliottech/lighter-python.git
```

### 问题: WebSocket 连接失败
**解决**:
- 检查网络连接
- WebSocket 会自动重连 (5秒延迟)
- 查看日志了解具体错误

### 问题: 对冲失败
**解决**:
1. 机器人会自动停止
2. 检查 `logs/standx_maker_hedger.log`
3. 手动在 Lighter 上对冲
4. 修复问题后重启

### 问题: "SOLANA_PRIVATE_KEY must be set"
**解决**:
- 确保 `.env` 文件存在
- 确保变量名正确
- 确保私钥格式是 Base58

## 📚 文档

- **使用指南**: [README_UPDATED.md](README_UPDATED.md)
- **配置示例**: [.env.example](.env.example)

## 🔗 技术栈

- Python 3.8+
- StandX API (Solana)
- Lighter SDK
- asyncio, websockets

## ✅ 验证清单

安装完成后验证:
- [ ] `.env` 文件已创建并填写凭证
- [ ] 虚拟环境已激活
- [ ] 依赖已安装 (`pip list | grep lighter`)
- [ ] Lighter SDK 可用
- [ ] `logs/` 目录已创建
- [ ] `start.sh` 有执行权限

## 🎊 总结

一个做市对冲系统:

✅ **StandX 客户端**: WebSocket + REST API
✅ **Lighter 客户端**: 官方 SDK
✅ **异步架构**: 高性能，实时响应
✅ **风险管理**: 多重安全保护
✅ **完整文档**: 详细的使用说明

只需配置好 `.env` 文件，就可以立即运行！

---

**下一步**:
1. 运行 `./setup.sh` 安装
2. 编辑 `.env` 填入凭证
3. 运行 `./start.sh` 启动
4. 监控 `logs/standx_maker_hedger.log`
