# 第三章：网络架构

## 3.1 网络模型选择

### 3.1.1 通信协议对比

| 协议 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| TCP | 可靠、有序 | 延迟高、队头阻塞 | 回合制、聊天 |
| UDP | 低延迟、无阻塞 | 不可靠、乱序 | 实时对战 |
| WebSocket | 穿透防火墙、易实现 | 基于TCP、延迟较高 | Web游戏 |
| QUIC | UDP基础、可靠、低延迟 | 较新、支持有限 | 未来方案 |

**帧同步推荐**：UDP（原生）或 WebSocket（Web/易实现）

### 3.1.2 拓扑结构

```
方案1：中心服务器（推荐）
┌─────────────────────────────────┐
│           Game Server           │
│        （权威帧管理）            │
└─────────────────────────────────┘
    │         │         │
    ▼         ▼         ▼
 Client A  Client B  Client C

优点：易实现、可验证、防作弊
缺点：服务器成本


方案2：P2P（不推荐）
    Client A
    /   |   \
   /    |    \
  ◀─────▶    ◀─────▶
Client B  ◀─────▶  Client C

优点：无服务器成本
缺点：NAT穿透、难以防作弊
```

## 3.2 协议设计

### 3.2.1 消息类型定义

```python
from enum import IntEnum
from dataclasses import dataclass
from typing import List, Dict, Optional
import struct
import msgpack

class MessageType(IntEnum):
    """消息类型"""
    # 连接相关
    JOIN_ROOM = 1
    LEAVE_ROOM = 2
    PLAYER_JOINED = 3
    PLAYER_LEFT = 4
    
    # 帧同步
    INPUT_FRAME = 10       # 客户端上传输入
    GAME_FRAME = 11        # 服务端下发帧数据
    FRAME_ACK = 12         # 帧确认
    
    # 同步控制
    SYNC_START = 20        # 开始同步
    SYNC_PAUSE = 21        # 暂停
    SYNC_RESUME = 22       # 恢复
    SYNC_SEEK = 23         # 跳转
    
    # 状态校验
    STATE_HASH = 30        # 状态哈希
    HASH_MISMATCH = 31     # 哈希不匹配
    
    # 错误处理
    ERROR = 40
    RECONNECT = 41

@dataclass
class InputFrame:
    """客户端输入帧"""
    frame_id: int          # 帧ID
    player_id: int         # 玩家ID
    input_data: bytes      # 输入数据（二进制）
    timestamp: int         # 时间戳

@dataclass
class GameFrame:
    """游戏帧（服务端下发）"""
    frame_id: int
    inputs: Dict[int, bytes]  # {player_id: input_data}
    confirmed: bool         # 是否已确认所有玩家

@dataclass  
class ProtocolMessage:
    """协议消息封装"""
    msg_type: MessageType
    payload: bytes
    sequence: int = 0      # 消息序号
```

### 3.2.2 高效序列化

```python
class FrameSerializer:
    """帧数据序列化器"""
    
    # 输入帧格式：frame_id(4) + player_id(1) + input_len(1) + input_data
    INPUT_FORMAT = '!IBB'  # network byte order
    
    @staticmethod
    def serialize_input(frame: InputFrame) -> bytes:
        """序列化输入帧"""
        header = struct.pack(
            FrameSerializer.INPUT_FORMAT,
            frame.frame_id,
            frame.player_id,
            len(frame.input_data)
        )
        return header + frame.input_data
    
    @staticmethod
    def deserialize_input(data: bytes) -> InputFrame:
        """反序列化输入帧"""
        header_size = struct.calcsize(FrameSerializer.INPUT_FORMAT)
        frame_id, player_id, input_len = struct.unpack(
            FrameSerializer.INPUT_FORMAT,
            data[:header_size]
        )
        input_data = data[header_size:header_size + input_len]
        return InputFrame(frame_id, player_id, input_data, 0)

    @staticmethod
    def serialize_game_frame(frame: GameFrame) -> bytes:
        """序列化游戏帧（使用msgpack）"""
        return msgpack.packb({
            'f': frame.frame_id,
            'i': {k: list(v) for k, v in frame.inputs.items()},
            'c': frame.confirmed
        }, use_bin_type=True)
    
    @staticmethod
    def deserialize_game_frame(data: bytes) -> GameFrame:
        """反序列化游戏帧"""
        obj = msgpack.unpackb(data, raw=False)
        return GameFrame(
            frame_id=obj['f'],
            inputs={k: bytes(v) for k, v in obj['i'].items()},
            confirmed=obj['c']
        )
```

## 3.3 帧缓冲机制

### 3.3.1 为什么需要帧缓冲？

```
无缓冲：RTT延迟直接变成输入延迟
Client A 发送输入 ────(50ms)────▶ Server
Client A ◀─── 等待其他玩家 ────── (100ms)
Client A 收到帧 ◀───(50ms)─────── Server
总延迟：200ms，玩家感觉迟钝

有缓冲：提前执行，抵消延迟
帧缓冲 = 3帧 = 100ms（假设33ms/帧）
实际感觉延迟 = RTT - 缓冲 = 100ms
```

### 3.3.2 帧缓冲实现

```python
class FrameBuffer:
    """帧缓冲管理器"""
    
    def __init__(self, buffer_size: int = 3):
        self.buffer_size = buffer_size
        self.frames: Dict[int, GameFrame] = {}
        self.pending_inputs: Dict[int, Dict[int, bytes]] = {}
        
    def add_input(self, frame_id: int, player_id: int, input_data: bytes):
        """添加玩家输入"""
        if frame_id not in self.pending_inputs:
            self.pending_inputs[frame_id] = {}
        self.pending_inputs[frame_id][player_id] = input_data
    
    def try_commit_frame(self, frame_id: int, player_count: int) -> Optional[GameFrame]:
        """尝试提交帧（所有玩家输入到齐）"""
        if frame_id not in self.pending_inputs:
            return None
        
        pending = self.pending_inputs[frame_id]
        if len(pending) == player_count:
            # 所有玩家输入到齐
            frame = GameFrame(
                frame_id=frame_id,
                inputs=dict(pending),
                confirmed=True
            )
            self.frames[frame_id] = frame
            del self.pending_inputs[frame_id]
            return frame
        
        return None
    
    def get_frame(self, frame_id: int) -> Optional[GameFrame]:
        """获取帧数据"""
        return self.frames.get(frame_id)
    
    def get_ready_frame(self, current_frame: int) -> int:
        """获取当前可执行的帧ID"""
        # 当前帧 = 服务器帧 - 缓冲大小
        return current_frame - self.buffer_size
    
    def cleanup_old_frames(self, oldest_frame: int):
        """清理旧帧"""
        for frame_id in list(self.frames.keys()):
            if frame_id < oldest_frame:
                del self.frames[frame_id]
        for frame_id in list(self.pending_inputs.keys()):
            if frame_id < oldest_frame:
                del self.pending_inputs[frame_id]
```

### 3.3.3 动态帧缓冲

根据网络状况动态调整：

```python
class AdaptiveFrameBuffer:
    """自适应帧缓冲"""
    
    def __init__(self, min_buffer=2, max_buffer=6):
        self.min_buffer = min_buffer
        self.max_buffer = max_buffer
        self.current_buffer = 3
        self.rtt_history = []
    
    def update_rtt(self, rtt_ms: float):
        """更新RTT统计"""
        self.rtt_history.append(rtt_ms)
        if len(self.rtt_history) > 30:
            self.rtt_history.pop(0)
        self._adjust_buffer()
    
    def _adjust_buffer(self):
        """动态调整缓冲大小"""
        if len(self.rtt_history) < 10:
            return
        
        avg_rtt = sum(self.rtt_history) / len(self.rtt_history)
        frame_time = 33  # 33ms per frame
        
        # 缓冲 = ceil(RTT / 帧时间) + 1
        target_buffer = int(avg_rtt / frame_time) + 1
        target_buffer = max(self.min_buffer, min(self.max_buffer, target_buffer))
        
        # 平滑调整
        if target_buffer > self.current_buffer:
            self.current_buffer += 1
        elif target_buffer < self.current_buffer:
            self.current_buffer -= 1
```

## 3.4 网络连接管理

### 3.4.1 连接状态机

```python
from enum import IntEnum
import asyncio

class ConnectionState(IntEnum):
    """连接状态"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    SYNCING = 3      # 同步中
    IN_GAME = 4      # 游戏中
    RECONNECTING = 5 # 重连中

class Connection:
    """网络连接管理"""
    
    def __init__(self):
        self.state = ConnectionState.DISCONNECTED
        self.websocket = None
        self.last_recv_time = 0
        self.last_send_time = 0
        self.msg_sequence = 0
        self.ack_window = {}  # 待确认消息
        
    async def connect(self, url: str):
        """建立连接"""
        self.state = ConnectionState.CONNECTING
        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(url),
                timeout=10.0
            )
            self.state = ConnectionState.CONNECTED
            self.last_recv_time = time.time()
            return True
        except Exception as e:
            self.state = ConnectionState.DISCONNECTED
            return False
    
    async def send_reliable(self, msg_type: MessageType, payload: bytes):
        """可靠发送（带重试）"""
        self.msg_sequence += 1
        msg = ProtocolMessage(
            msg_type=msg_type,
            payload=payload,
            sequence=self.msg_sequence
        )
        
        # 记录待确认
        self.ack_window[self.msg_sequence] = {
            'msg': msg,
            'send_time': time.time(),
            'retries': 0
        }
        
        await self._send_raw(msg)
    
    async def _send_raw(self, msg: ProtocolMessage):
        """底层发送"""
        data = msgpack.packb({
            't': msg.msg_type,
            'p': msg.payload,
            's': msg.sequence
        })
        await self.websocket.send(data)
        self.last_send_time = time.time()
    
    async def recv(self) -> Optional[ProtocolMessage]:
        """接收消息"""
        try:
            data = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            self.last_recv_time = time.time()
            
            obj = msgpack.unpackb(data)
            return ProtocolMessage(
                msg_type=MessageType(obj['t']),
                payload=obj['p'],
                sequence=obj.get('s', 0)
            )
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self.state = ConnectionState.DISCONNECTED
            return None
```

### 3.4.2 心跳与超时

```python
class HeartbeatManager:
    """心跳管理"""
    
    HEARTBEAT_INTERVAL = 1.0   # 心跳间隔
    HEARTBEAT_TIMEOUT = 5.0    # 超时时间
    
    def __init__(self, connection: Connection):
        self.connection = connection
        self.last_heartbeat = 0
        self.missed_heartbeats = 0
    
    async def run(self):
        """心跳协程"""
        while self.connection.state != ConnectionState.DISCONNECTED:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            
            # 检查超时
            time_since_recv = time.time() - self.connection.last_recv_time
            if time_since_recv > self.HEARTBEAT_TIMEOUT:
                self.missed_heartbeats += 1
                if self.missed_heartbeats >= 3:
                    self.connection.state = ConnectionState.DISCONNECTED
                    return
            
            # 发送心跳
            await self.connection.send_reliable(
                MessageType.HEARTBEAT,
                b''
            )
            self.last_heartbeat = time.time()
```

## 3.5 断线重连

### 3.5.1 重连流程

```
1. 检测断线
2. 尝试重连
3. 发送 RECONNECT 消息（带上玩家ID和房间ID）
4. 服务端验证
5. 服务端发送缺失的帧数据
6. 客户端快速追帧
7. 恢复正常同步
```

### 3.5.2 重连实现

```python
class ReconnectManager:
    """重连管理"""
    
    MAX_RETRIES = 5
    RETRY_DELAY = 1.0
    
    def __init__(self, connection: Connection, game_state):
        self.connection = connection
        self.game_state = game_state
        self.frame_history = []  # 保存最近帧用于追帧
    
    async def handle_disconnect(self):
        """处理断线"""
        self.connection.state = ConnectionState.RECONNECTING
        
        for retry in range(self.MAX_RETRIES):
            await asyncio.sleep(self.RETRY_DELAY * (retry + 1))
            
            if await self.connection.connect(self.connection.url):
                # 重连成功，请求同步
                await self._request_resync()
                return True
        
        self.connection.state = ConnectionState.DISCONNECTED
        return False
    
    async def _request_resync(self):
        """请求重新同步"""
        reconnect_msg = msgpack.packb({
            'player_id': self.game_state.player_id,
            'room_id': self.game_state.room_id,
            'last_frame': self.game_state.last_confirmed_frame
        })
        
        await self.connection.send_reliable(
            MessageType.RECONNECT,
            reconnect_msg
        )
    
    def fast_forward(self, frames: List[GameFrame]):
        """快速追帧"""
        for frame in frames:
            self.game_state.apply_frame(frame)
```

## 3.6 本章小结

- 选择合适的协议（UDP/WebSocket）和拓扑（中心服务器）
- 设计高效的消息格式和序列化方案
- 帧缓冲抵消网络延迟，动态调整优化体验
- 完善的连接管理、心跳和重连机制

---

**下一章**：[延迟优化](04-optimization.md) - 客户端预测与延迟补偿
