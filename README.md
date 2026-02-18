# Game Frame Sync - 游戏帧同步技术学习项目

> 从0到1学习游戏帧同步技术，Python 生产级实现

## 📚 项目简介

本项目旨在帮助开发者系统学习游戏帧同步技术，从基础概念到生产级实现，包含完整的服务端、客户端代码和详细文档。

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
│   └── main.py             # 服务入口
├── client/                 # 客户端示例
│   └── game_client.py      # 网络客户端
├── core/                   # 核心同步逻辑
│   ├── frame.py            # 帧数据结构
│   ├── input.py            # 输入处理
│   ├── physics.py          # 确定性物理
│   ├── state.py            # 游戏状态
│   └── rng.py              # 确定性随机数
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

---

## 📐 UML 架构图

### 1. 系统架构图

```mermaid
graph TB
    subgraph 客户端层
        C1[Client 1]
        C2[Client 2]
        C3[Client N]
    end
    
    subgraph 网关层
        GW[WebSocket Gateway]
    end
    
    subgraph 服务层
        GS[Game Server]
        RM[Room Manager]
        FE[Frame Engine]
    end
    
    subgraph 存储层
        Redis[(Redis)]
    end
    
    C1 -->|WebSocket| GW
    C2 -->|WebSocket| GW
    C3 -->|WebSocket| GW
    
    GW --> GS
    GS --> RM
    RM --> FE
    
    GS --> Redis
    
    style GW fill:#e1f5fe
    style FE fill:#fff3e0
    style Redis fill:#e8f5e9
```

### 2. 帧同步时序图

```mermaid
sequenceDiagram
    participant C1 as Client 1
    participant S as Server
    participant C2 as Client 2
    
    Note over C1,C2: 帧 N 开始
    
    C1->>S: Input[N] (玩家1输入)
    C2->>S: Input[N] (玩家2输入)
    
    Note over S: 收集所有玩家输入<br/>打包成帧
    
    S->>C1: Frame[N] {inputs: [1,2]}
    S->>C2: Frame[N] {inputs: [1,2]}
    
    Note over C1,C2: 执行确定性逻辑<br/>状态保持一致
    
    Note over C1,C2: 帧 N+1 开始
    
    C1->>S: Input[N+1]
    C2->>S: Input[N+1]
    
    S->>C1: Frame[N+1]
    S->>C2: Frame[N+1]
```

### 3. 客户端预测与回滚

```mermaid
sequenceDiagram
    participant C as Client
    participant P as Predictor
    participant S as Server
    
    Note over C,S: 客户端预测流程
    
    C->>P: 玩家输入
    P->>P: 保存快照
    P->>P: 预测其他玩家输入
    P->>C: 立即执行预测帧
    
    Note over C,S: 服务器确认到达
    
    S->>C: 真实帧数据
    
    alt 预测正确
        C->>C: 继续执行
    else 预测错误
        C->>P: 回滚到快照
        P->>C: 应用真实输入
        P->>C: 重放后续帧
    end
```

### 4. 核心类图

```mermaid
classDiagram
    class FrameEngine {
        -int current_frame
        -FrameBuffer frame_buffer
        -int player_count
        +add_input(frame_id, player_id, input)
        +tick() Frame
        +force_tick() Frame
        +get_stats() dict
    }
    
    class FrameBuffer {
        -int buffer_size
        -dict frames
        -dict pending_inputs
        +add_input(frame_id, player_id, input)
        +try_commit_frame(frame_id, player_count) Frame
        +get_frame(frame_id) Frame
        +cleanup_old_frames(oldest)
    }
    
    class Frame {
        +int frame_id
        +dict inputs
        +bool confirmed
        +get_input(player_id) bytes
        +set_input(player_id, data)
        +is_complete(player_count) bool
    }
    
    class PhysicsEngine {
        -dict entities
        -list collision_pairs
        +add_entity(entity)
        +remove_entity(entity_id)
        +update(dt_ms)
        +apply_input(entity_id, flags)
    }
    
    class Entity {
        +int entity_id
        +int x, y
        +int vx, vy
        +int hp
        +update_position(dt_ms)
        +serialize() dict
        +deserialize(data)
    }
    
    class DeterministicRNG {
        -int state
        +next_uint32() int
        +range(min, max) int
        +uniform() float
        +shuffle(list)
    }
    
    class GameState {
        +int frame_id
        +dict entities
        +save_snapshot() Snapshot
        +restore_snapshot(frame_id)
        +compute_state_hash() str
    }
    
    FrameEngine --> FrameBuffer : uses
    FrameEngine --> Frame : creates
    FrameBuffer --> Frame : stores
    PhysicsEngine --> Entity : manages
    GameState --> Entity : contains
    GameState --> StateSnapshot : creates
    PhysicsEngine ..> DeterministicRNG : uses
```

### 5. 游戏状态机

```mermaid
stateDiagram-v2
    [*] --> Disconnected: 初始化
    
    Disconnected --> Connecting: connect()
    Connecting --> Connected: 连接成功
    Connecting --> Disconnected: 连接失败
    
    Connected --> Syncing: join_room()
    Syncing --> WaitingPlayers: 等待玩家
    WaitingPlayers --> InGame: 玩家到齐
    
    InGame --> Paused: 暂停
    Paused --> InGame: resume()
    
    InGame --> Reconnecting: 断线
    Reconnecting --> InGame: 重连成功
    Reconnecting --> Disconnected: 重连失败
    
    InGame --> Disconnected: leave()
    Connected --> Disconnected: disconnect()
    Disconnected --> [*]: 销毁
```

### 6. 网络协议消息流

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    
    rect rgb(240, 248, 255)
        Note over C,S: 连接阶段
        C->>S: {type: auth, player_id, room_id}
        S->>C: {type: join_success, room_id, players}
        S->>C: {type: player_joined, player_id}
    end
    
    rect rgb(255, 250, 240)
        Note over C,S: 游戏进行中
        loop 每帧 (30fps)
            C->>S: {type: input, frame_id, input_data}
            S->>S: 收集所有输入
            S->>C: {type: game_frame, frame_id, inputs}
        end
    end
    
    rect rgb(240, 255, 240)
        Note over C,S: 状态校验
        C->>S: {type: state_hash, frame_id, hash}
        S->>S: 验证哈希
        alt 哈希不匹配
            S->>C: {type: hash_mismatch, frame_id}
        end
    end
    
    rect rgb(255, 240, 245)
        Note over C,S: 断线重连
        C->>S: {type: reconnect, player_id, last_frame}
        S->>C: {type: sync_frames, frames[]}
        C->>C: 快速追帧
    end
```

### 7. 帧缓冲工作原理

```mermaid
graph LR
    subgraph 时间线
        T0[T-2] --> T1[T-1] --> T2[T] --> T3[T+1] --> T4[T+2]
    end
    
    subgraph 帧缓冲区
        B1[已确认帧] 
        B2[已确认帧]
        B3[待确认帧]
    end
    
    subgraph 执行区
        E1[正在执行]
    end
    
    T0 --> B1
    T1 --> B2
    T2 --> B3
    B1 --> E1
    
    style B1 fill:#c8e6c9
    style B2 fill:#c8e6c9
    style B3 fill:#fff9c4
    style E1 fill:#bbdefb
```

### 8. 确定性物理更新循环

```mermaid
flowchart TD
    A[开始帧更新] --> B{帧缓冲是否充足?}
    B -->|否| C[等待更多帧]
    B -->|是| D[获取下一帧输入]
    
    D --> E[应用玩家输入到实体]
    E --> F[更新物理引擎]
    
    F --> G[应用重力]
    G --> H[更新速度]
    H --> I[更新位置]
    I --> J[边界碰撞检测]
    J --> K[实体间碰撞检测]
    K --> L[解决碰撞]
    
    L --> M[保存状态快照]
    M --> N{需要校验?}
    
    N -->|是| O[计算状态哈希]
    O --> P{哈希匹配?}
    P -->|否| Q[触发不同步处理]
    P -->|是| R[帧结束]
    
    N -->|否| R
    Q --> R
    C --> A
```

---

## 🔍 技术卡点速查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 状态不同步 | 浮点数精度差异 | 使用定点数 |
| 随机结果不同 | 随机序列不一致 | 同步种子 + 确定性RNG |
| 画面卡顿 | 网络延迟波动 | 帧缓冲 + 客户端预测 |
| 预测误差大 | 其他玩家行为难预测 | 智能预测算法 |
| 断线无法恢复 | 状态丢失 | 帧历史 + 状态同步 |
| 作弊检测难 | 客户端权威 | 哈希校验 + 多数投票 |

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 License

MIT License
