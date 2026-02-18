# Game Frame Sync - 游戏帧同步技术学习项目

> 从0到1学习游戏帧同步技术，Python 生产级实现

## 📚 项目简介

本项目旨在帮助开发者系统学习游戏帧同步技术，从基础概念到生产级实现，包含完整的服务端、客户端代码和详细文档。

## 🎯 学习目标

- 理解帧同步的核心原理
- 掌握确定性物理模拟
- 学会处理网络延迟和抖动
- 实现客户端预测和服务器回滚
- 构建生产级帧同步系统

## 📖 文档目录

| 章节 | 内容 | 难度 |
|------|------|------|
| [01-基础概念](docs/01-basics.md) | 帧同步 vs 状态同步，核心原理 | ⭐ |
| [02-确定性模拟](docs/02-determinism.md) | 浮点数问题，随机数同步 | ⭐⭐ |
| [03-网络架构](docs/03-network.md) | 协议设计，帧缓冲 | ⭐⭐ |
| [04-延迟优化](docs/04-optimization.md) | 客户端预测，延迟补偿 | ⭐⭐⭐ |
| [05-技术卡点](docs/05-challenges.md) | 常见问题与解决方案 | ⭐⭐⭐ |
| [06-生产实践](docs/06-production.md) | 性能优化，容错处理 | ⭐⭐⭐⭐ |

## 🏗️ 项目结构

```
game-frame-sync/
├── server/                 # 帧同步服务端
│   ├── room_manager.py     # 房间管理
│   ├── frame_engine.py     # 帧同步引擎
│   ├── connection.py       # 网络连接管理
│   └── main.py             # 服务入口
├── client/                 # 客户端示例
│   ├── game_client.py      # 网络客户端
│   ├── predictor.py        # 客户端预测
│   └── renderer.py         # 渲染器（PyGame）
├── core/                   # 核心同步逻辑
│   ├── frame.py            # 帧数据结构
│   ├── input.py            # 输入处理
│   ├── physics.py          # 确定性物理
│   └── state.py            # 游戏状态
├── docs/                   # 文档
├── tests/                  # 单元测试
├── config/                 # 配置文件
└── scripts/                # 辅助脚本
```

## 🚀 快速开始

```bash
# 克隆项目
git clone https://github.com/kongshan001/game-frame-sync.git
cd game-frame-sync

# 安装依赖
pip install -r requirements.txt

# 启动服务端
python -m server.main

# 启动客户端（另一个终端）
python -m client.game_client
```

## 🔧 技术栈

- **Python 3.10+**
- **asyncio** - 异步网络 IO
- **websockets** - WebSocket 通信
- **msgpack** - 高效二进制序列化
- **pytest** - 单元测试

## 📋 核心特性

- ✅ 确定性物理模拟
- ✅ 帧缓冲与延迟补偿
- ✅ 客户端预测
- ✅ 服务器权威校验
- ✅ 断线重连
- ✅ 回放系统
- ✅ 性能监控

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 License

MIT License
