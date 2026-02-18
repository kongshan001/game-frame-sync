# 第六章：生产实践

## 6.1 生产环境要求

### 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 服务器单房间帧率 | 稳定 30fps | 每帧处理时间 < 33ms |
| 服务器并发房间 | 1000+ | 4核8G 配置 |
| 网络带宽/房间 | < 10KB/s | 4人房间 |
| 客户端帧率 | 稳定 60fps | 渲染帧 |
| 状态同步延迟 | < 100ms | 从输入到反馈 |
| 内存占用/房间 | < 10MB | 包含帧历史 |

## 6.2 架构设计

### 6.2.1 服务器架构

```
┌─────────────────────────────────────────────────────┐
│                    Load Balancer                     │
└─────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  Gateway 1    │ │  Gateway 2    │ │  Gateway N    │
│  (WebSocket)  │ │  (WebSocket)  │ │  (WebSocket)  │
└───────────────┘ └───────────────┘ └───────────────┘
        │                │                │
        └────────────────┼────────────────┘
                         ▼
┌─────────────────────────────────────────────────────┐
│              Game Server Cluster                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │ Room 1  │  │ Room 2  │  │ Room N  │            │
│  │ Room 3  │  │ Room 4  │  │ ...     │            │
│  └─────────┘  └─────────┘  └─────────┘            │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Redis (State / PubSub)                 │
└─────────────────────────────────────────────────────┘
```

### 6.2.2 服务器实现

```python
# server/main.py
import asyncio
import signal
from typing import Dict, Set
from dataclasses import dataclass
import msgpack
import redis.asyncio as redis

@dataclass
class Room:
    """游戏房间"""
    room_id: str
    players: Set[str]
    frame_engine: 'FrameEngine'
    created_at: float

class GameServer:
    """生产级帧同步服务器"""
    
    def __init__(self, config: dict):
        self.config = config
        self.rooms: Dict[str, Room] = {}
        self.player_rooms: Dict[str, str] = {}  # player_id -> room_id
        self.connections: Dict[str, 'WebSocket'] = {}
        self.redis = None
        self.running = False
        
    async def start(self):
        """启动服务器"""
        # 连接 Redis
        self.redis = await redis.from_url(
            self.config.get('redis_url', 'redis://localhost')
        )
        
        # 启动 WebSocket 服务
        host = self.config.get('host', '0.0.0.0')
        port = self.config.get('port', 8765)
        
        self.running = True
        print(f"Server starting on {host}:{port}")
        
        async with websockets.serve(
            self._handle_connection,
            host,
            port,
            ping_interval=20,
            ping_timeout=10
        ):
            # 启动帧循环
            asyncio.create_task(self._frame_loop())
            
            # 等待停止信号
            await self._wait_shutdown()
    
    async def _handle_connection(self, websocket, path):
        """处理客户端连接"""
        player_id = None
        try:
            # 认证
            auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            player_id = await self._authenticate(auth_msg, websocket)
            
            if not player_id:
                await websocket.close(4001, "Authentication failed")
                return
            
            self.connections[player_id] = websocket
            
            # 消息循环
            async for message in websocket:
                await self._handle_message(player_id, message)
                
        except asyncio.TimeoutError:
            await websocket.close(4002, "Authentication timeout")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if player_id:
                await self._handle_disconnect(player_id)
    
    async def _handle_message(self, player_id: str, message: bytes):
        """处理客户端消息"""
        try:
            data = msgpack.unpackb(message, raw=False)
            msg_type = data.get('type')
            payload = data.get('payload', {})
            
            if msg_type == 'join_room':
                await self._join_room(player_id, payload)
            elif msg_type == 'input':
                await self._handle_input(player_id, payload)
            elif msg_type == 'leave_room':
                await self._leave_room(player_id)
            
        except Exception as e:
            print(f"Error handling message: {e}")
    
    async def _join_room(self, player_id: str, payload: dict):
        """加入房间"""
        room_id = payload.get('room_id')
        
        if room_id not in self.rooms:
            self.rooms[room_id] = Room(
                room_id=room_id,
                players=set(),
                frame_engine=FrameEngine(),
                created_at=time.time()
            )
        
        room = self.rooms[room_id]
        room.players.add(player_id)
        self.player_rooms[player_id] = room_id
        
        # 通知房间内所有玩家
        await self._broadcast_to_room(room_id, {
            'type': 'player_joined',
            'payload': {'player_id': player_id}
        })
        
        # 如果房间满员，开始游戏
        if len(room.players) >= self.config.get('max_players', 4):
            await self._start_game(room_id)
    
    async def _handle_input(self, player_id: str, payload: dict):
        """处理玩家输入"""
        room_id = self.player_rooms.get(player_id)
        if not room_id:
            return
        
        room = self.rooms[room_id]
        frame_id = payload.get('frame_id')
        input_data = payload.get('input_data')
        
        # 添加到帧引擎
        room.frame_engine.add_input(frame_id, player_id, input_data)
    
    async def _frame_loop(self):
        """帧循环（30fps）"""
        frame_time = 1.0 / 30  # 33ms
        
        while self.running:
            frame_start = time.time()
            
            # 处理所有房间
            for room_id, room in list(self.rooms.items()):
                try:
                    frame = room.frame_engine.tick()
                    if frame:
                        await self._broadcast_frame(room_id, frame)
                except Exception as e:
                    print(f"Error in room {room_id}: {e}")
            
            # 精确帧率控制
            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
    
    async def _broadcast_frame(self, room_id: str, frame):
        """广播帧数据"""
        message = msgpack.packb({
            'type': 'game_frame',
            'payload': {
                'frame_id': frame.frame_id,
                'inputs': frame.inputs,
                'confirmed': frame.confirmed
            }
        })
        
        await self._broadcast_to_room(room_id, message, binary=True)
    
    async def _broadcast_to_room(self, room_id: str, message, binary=False):
        """向房间广播消息"""
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        tasks = []
        
        for player_id in room.players:
            if player_id in self.connections:
                ws = self.connections[player_id]
                if binary:
                    tasks.append(ws.send(message))
                else:
                    tasks.append(ws.send(msgpack.packb(message)))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _handle_disconnect(self, player_id: str):
        """处理断线"""
        if player_id in self.connections:
            del self.connections[player_id]
        
        room_id = self.player_rooms.get(player_id)
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            room.players.discard(player_id)
            
            # 通知其他玩家
            await self._broadcast_to_room(room_id, {
                'type': 'player_left',
                'payload': {'player_id': player_id}
            })
            
            # 如果房间空了，清理
            if not room.players:
                del self.rooms[room_id]
        
        if player_id in self.player_rooms:
            del self.player_rooms[player_id]
    
    async def _wait_shutdown(self):
        """等待关闭信号"""
        loop = asyncio.get_event_loop()
        stop = loop.create_future()
        
        def signal_handler():
            stop.set_result(None)
        
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        
        await stop
        self.running = False
        print("Server shutting down...")

# 启动入口
if __name__ == '__main__':
    config = {
        'host': '0.0.0.0',
        'port': 8765,
        'redis_url': 'redis://localhost',
        'max_players': 4
    }
    
    server = GameServer(config)
    asyncio.run(server.start())
```

## 6.3 容错处理

### 6.3.1 异常处理框架

```python
import logging
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)

class FrameSyncError(Exception):
    """帧同步基础异常"""
    pass

class NetworkError(FrameSyncError):
    """网络异常"""
    pass

class StateDesyncError(FrameSyncError):
    """状态不同步异常"""
    pass

class InputValidationError(FrameSyncError):
    """输入验证异常"""
    pass

def retry_on_error(max_retries: int = 3, delay: float = 0.1):
    """重试装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except NetworkError as e:
                    last_error = e
                    logger.warning(f"Retry {attempt + 1}/{max_retries}: {e}")
                    await asyncio.sleep(delay * (attempt + 1))
                except Exception as e:
                    # 非网络错误不重试
                    raise
            
            raise last_error or NetworkError("Max retries exceeded")
        return wrapper
    return decorator

class ErrorRecovery:
    """错误恢复"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.error_count = {}
        self.max_errors = 10
    
    async def handle_error(self, error: Exception, context: dict):
        """处理错误"""
        error_type = type(error).__name__
        
        # 记录错误
        self.error_count[error_type] = self.error_count.get(error_type, 0) + 1
        logger.error(f"Error {error_type}: {error}", extra=context)
        
        # 错误频率检查
        if self.error_count[error_type] > self.max_errors:
            logger.critical(f"Too many {error_type} errors, stopping")
            return False
        
        # 根据错误类型恢复
        if isinstance(error, StateDesyncError):
            return await self._recover_from_desync(error, context)
        elif isinstance(error, NetworkError):
            return await self._recover_from_network_error(error, context)
        
        return True
    
    async def _recover_from_desync(self, error, context):
        """从状态不同步恢复"""
        logger.info("Attempting desync recovery")
        
        # 请求完整状态同步
        await self.game_state.request_full_sync()
        
        # 重置错误计数
        self.error_count[type(error).__name__] = 0
        
        return True
    
    async def _recover_from_network_error(self, error, context):
        """从网络错误恢复"""
        logger.info("Attempting network recovery")
        
        # 尝试重连
        if await self.game_state.reconnect():
            self.error_count[type(error).__name__] = 0
            return True
        
        return False
```

### 6.3.2 监控与告警

```python
from dataclasses import dataclass, field
from typing import List
import statistics

@dataclass
class Metrics:
    """性能指标"""
    frame_times: List[float] = field(default_factory=list)
    network_rtt: List[float] = field(default_factory=list)
    player_count: int = 0
    room_count: int = 0
    error_count: int = 0

class MetricsCollector:
    """指标收集器"""
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.metrics = Metrics()
    
    def record_frame_time(self, frame_time: float):
        """记录帧时间"""
        self.metrics.frame_times.append(frame_time)
        if len(self.metrics.frame_times) > self.window_size:
            self.metrics.frame_times.pop(0)
    
    def record_rtt(self, rtt: float):
        """记录 RTT"""
        self.metrics.network_rtt.append(rtt)
        if len(self.metrics.network_rtt) > self.window_size:
            self.metrics.network_rtt.pop(0)
    
    def get_stats(self) -> dict:
        """获取统计"""
        frame_times = self.metrics.frame_times
        rtts = self.metrics.network_rtt
        
        return {
            'frame_time': {
                'mean': statistics.mean(frame_times) if frame_times else 0,
                'max': max(frame_times) if frame_times else 0,
                'p99': statistics.quantiles(frame_times, n=100)[98] if len(frame_times) > 10 else 0
            },
            'network': {
                'mean_rtt': statistics.mean(rtts) if rtts else 0,
                'max_rtt': max(rtts) if rtts else 0
            },
            'counts': {
                'players': self.metrics.player_count,
                'rooms': self.metrics.room_count,
                'errors': self.metrics.error_count
            }
        }

class AlertManager:
    """告警管理"""
    
    def __init__(self, thresholds: dict):
        self.thresholds = thresholds
        self.alerts = []
    
    def check_and_alert(self, stats: dict):
        """检查并告警"""
        # 帧时间告警
        if stats['frame_time']['mean'] > self.thresholds.get('frame_time_warning', 30):
            self._alert('warning', f"High frame time: {stats['frame_time']['mean']:.2f}ms")
        
        if stats['frame_time']['max'] > self.thresholds.get('frame_time_critical', 50):
            self._alert('critical', f"Frame time spike: {stats['frame_time']['max']:.2f}ms")
        
        # 网络告警
        if stats['network']['mean_rtt'] > self.thresholds.get('rtt_warning', 100):
            self._alert('warning', f"High RTT: {stats['network']['mean_rtt']:.2f}ms")
    
    def _alert(self, level: str, message: str):
        """发送告警"""
        alert = {
            'level': level,
            'message': message,
            'timestamp': time.time()
        }
        self.alerts.append(alert)
        
        # 可以接入实际的告警系统（邮件、钉钉、Slack等）
        print(f"[{level.upper()}] {message}")
```

## 6.4 性能优化

### 6.4.1 内存优化

```python
import weakref
from collections import deque

class MemoryEfficientFrameHistory:
    """内存高效的帧历史"""
    
    def __init__(self, max_frames: int = 300):  # 10秒 @ 30fps
        self.frames = deque(maxlen=max_frames)
        self.compressed_frames = {}  # 旧帧压缩存储
    
    def add_frame(self, frame):
        """添加帧"""
        self.frames.append(frame)
        
        # 超过限制的旧帧压缩
        if len(self.frames) == self.frames.maxlen:
            old_frame = self.frames[0]
            compressed = self._compress_frame(old_frame)
            self.compressed_frames[old_frame.frame_id] = compressed
    
    def _compress_frame(self, frame) -> bytes:
        """压缩帧数据"""
        import zlib
        data = msgpack.packb({
            'f': frame.frame_id,
            'i': frame.inputs
        })
        return zlib.compress(data, level=9)
    
    def get_frame(self, frame_id: int):
        """获取帧"""
        # 先在活跃队列找
        for frame in self.frames:
            if frame.frame_id == frame_id:
                return frame
        
        # 再在压缩存储找
        if frame_id in self.compressed_frames:
            return self._decompress_frame(self.compressed_frames[frame_id])
        
        return None

class ObjectPool:
    """对象池"""
    
    def __init__(self, factory, initial_size: int = 100):
        self.factory = factory
        self.pool = [factory() for _ in range(initial_size)]
        self.active = weakref.WeakSet()
    
    def acquire(self):
        """获取对象"""
        if self.pool:
            obj = self.pool.pop()
        else:
            obj = self.factory()
        
        self.active.add(obj)
        return obj
    
    def release(self, obj):
        """释放对象"""
        obj.reset()  # 假设对象有 reset 方法
        self.pool.append(obj)
```

### 6.4.2 CPU 优化

```python
from typing import List
import cython  # 可选：使用 Cython 优化

class OptimizedPhysics:
    """优化的物理计算"""
    
    @staticmethod
    def batch_collision_check(entities: List['Entity']) -> List[tuple]:
        """批量碰撞检测"""
        collisions = []
        n = len(entities)
        
        # 空间分区优化
        grid = {}
        cell_size = 100
        
        for entity in entities:
            cell_x = int(entity.x // cell_size)
            cell_y = int(entity.y // cell_size)
            key = (cell_x, cell_y)
            
            if key not in grid:
                grid[key] = []
            grid[key].append(entity)
        
        # 只检查同一格子内的实体
        for key, cell_entities in grid.items():
            for i in range(len(cell_entities)):
                for j in range(i + 1, len(cell_entities)):
                    if OptimizedPhysics._check_aabb(cell_entities[i], cell_entities[j]):
                        collisions.append((cell_entities[i].id, cell_entities[j].id))
        
        return collisions
    
    @staticmethod
    def _check_aabb(a, b) -> bool:
        """AABB 碰撞检测"""
        return (a.x < b.x + b.width and
                a.x + a.width > b.x and
                a.y < b.y + b.height and
                a.y + a.height > b.y)

# 使用 __slots__ 减少内存
class Entity:
    """游戏实体"""
    __slots__ = ['id', 'x', 'y', 'vx', 'vy', 'width', 'height']
    
    def __init__(self, entity_id, x, y):
        self.id = entity_id
        self.x = x
        self.y = y
        self.vx = 0
        self.vy = 0
        self.width = 32
        self.height = 32
```

## 6.5 测试策略

### 6.5.1 单元测试

```python
# tests/test_frame_engine.py
import pytest
from server.frame_engine import FrameEngine, GameFrame

class TestFrameEngine:
    """帧引擎测试"""
    
    def test_add_input(self):
        """测试添加输入"""
        engine = FrameEngine()
        engine.add_input(1, 'player1', b'input1')
        
        assert 1 in engine.pending_inputs
        assert 'player1' in engine.pending_inputs[1]
    
    def test_frame_commit(self):
        """测试帧提交"""
        engine = FrameEngine(player_count=2)
        engine.add_input(1, 'player1', b'input1')
        engine.add_input(1, 'player2', b'input2')
        
        frame = engine.try_commit_frame(1)
        
        assert frame is not None
        assert frame.confirmed
        assert 'player1' in frame.inputs
        assert 'player2' in frame.inputs
    
    def test_partial_frame_not_committed(self):
        """测试部分输入不提交"""
        engine = FrameEngine(player_count=2)
        engine.add_input(1, 'player1', b'input1')
        
        frame = engine.try_commit_frame(1)
        
        assert frame is None  # 未满员不提交

# tests/test_determinism.py
class TestDeterminism:
    """确定性测试"""
    
    def test_rng_determinism(self):
        """测试随机数确定性"""
        from core.rng import DeterministicRNG
        
        rng1 = DeterministicRNG(12345)
        rng2 = DeterministicRNG(12345)
        
        for _ in range(100):
            assert rng1.range(0, 100) == rng2.range(0, 100)
    
    def test_physics_determinism(self):
        """测试物理确定性"""
        from core.physics import PhysicsEngine
        
        # 两个独立的物理引擎
        engine1 = PhysicsEngine()
        engine2 = PhysicsEngine()
        
        # 相同的初始状态
        engine1.add_entity(1, x=100, y=100)
        engine2.add_entity(1, x=100, y=100)
        
        # 相同的输入
        inputs = {1: b'move_right'}
        
        # 执行100帧
        for _ in range(100):
            engine1.apply_inputs(inputs)
            engine2.apply_inputs(inputs)
        
        # 验证状态一致
        e1 = engine1.get_entity(1)
        e2 = engine2.get_entity(1)
        
        assert e1.x == e2.x
        assert e1.y == e2.y

# tests/test_network.py
import asyncio
import pytest

class TestNetwork:
    """网络测试"""
    
    @pytest.mark.asyncio
    async def test_frame_buffer(self):
        """测试帧缓冲"""
        from core.frame_buffer import FrameBuffer
        
        buffer = FrameBuffer(buffer_size=2)
        
        # 添加输入
        buffer.add_input(1, 'player1', b'input1')
        buffer.add_input(1, 'player2', b'input2')
        
        # 提交帧
        frame = buffer.try_commit_frame(1, player_count=2)
        
        assert frame is not None
        assert frame.frame_id == 1

# 运行测试
# pytest tests/ -v --cov=. --cov-report=html
```

### 6.5.2 压力测试

```python
# tests/stress_test.py
import asyncio
import time
from server.main import GameServer

async def stress_test():
    """压力测试"""
    # 模拟 N 个客户端
    num_clients = 100
    clients = []
    
    for i in range(num_clients):
        client = await create_test_client(f"player_{i}")
        clients.append(client)
    
    # 运行 60 秒
    start_time = time.time()
    frame_count = 0
    
    while time.time() - start_time < 60:
        # 发送随机输入
        for client in clients:
            await client.send_random_input()
        
        await asyncio.sleep(0.033)  # 30fps
        frame_count += 1
    
    # 统计
    print(f"Frames: {frame_count}")
    print(f"Avg frame time: {(time.time() - start_time) / frame_count * 1000:.2f}ms")
    
    # 清理
    for client in clients:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(stress_test())
```

## 6.6 部署清单

### 6.6.1 部署前检查

```markdown
- [ ] 所有单元测试通过
- [ ] 压力测试通过（目标负载 2x）
- [ ] 代码覆盖率 > 80%
- [ ] 性能指标达标
- [ ] 日志系统配置完成
- [ ] 监控告警配置完成
- [ ] 备份恢复方案就绪
- [ ] 灰度发布计划就绪
```

### 6.6.2 Docker 部署

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8765

CMD ["python", "-m", "server.main"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  game-server:
    build: .
    ports:
      - "8765:8765"
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 2G
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

## 6.7 本章小结

生产级帧同步系统需要：
- ✅ 可扩展的服务器架构
- ✅ 完善的异常处理和恢复机制
- ✅ 性能监控和告警系统
- ✅ 内存和 CPU 优化
- ✅ 全面的测试覆盖
- ✅ 可靠的部署方案

---

**恭喜！** 你已经完成了帧同步技术的完整学习之旅。现在你已经掌握了：

1. 帧同步的核心原理
2. 如何实现确定性模拟
3. 网络协议和帧缓冲设计
4. 客户端预测和延迟优化
5. 常见技术卡点的解决方案
6. 生产环境的最佳实践

继续实践，构建你自己的帧同步游戏！
