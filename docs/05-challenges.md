# 第五章：技术卡点与解决方案

## 5.1 浮点数精度问题

### 问题描述
不同设备/CPU架构上的浮点运算结果可能存在细微差异，导致状态分叉。

### 解决方案

```python
# 方案1：定点数（推荐）
class FixedPoint:
    """16.16 定点数"""
    SCALE = 65536
    MASK = 0xFFFFFFFF
    
    def __init__(self, value=0):
        if isinstance(value, float):
            self.raw = int(value * self.SCALE) & self.MASK
        elif isinstance(value, int):
            self.raw = (value << 16) & self.MASK
        else:
            self.raw = value
    
    def __add__(self, other): return FixedPoint((self.raw + other.raw) & self.MASK)
    def __sub__(self, other): return FixedPoint((self.raw - other.raw) & self.MASK)
    def __mul__(self, other): return FixedPoint(((self.raw * other.raw) >> 16) & self.MASK)
    def __truediv__(self, other): return FixedPoint(((self.raw << 16) // other.raw) & self.MASK)
    
    def to_float(self): return self.raw / self.SCALE
    def to_int(self): return self.raw >> 16

# 方案2：确定性浮点（截断精度）
import struct
def deterministic_float(value):
    return struct.unpack('f', struct.pack('f', value))[0]

# 方案3：使用 decimal 模块
from decimal import Decimal, getcontext
getcontext().prec = 6  # 固定精度
```

### 最佳实践
- ✅ 位置、速度使用定点数
- ✅ 碰撞检测使用整数坐标
- ✅ 物理计算避免复杂浮点运算
- ❌ 不要直接比较浮点数相等

## 5.2 随机数同步

### 问题描述
每个客户端的随机序列不同，导致行为不一致。

### 解决方案

```python
class DeterministicRNG:
    """确定性随机数生成器"""
    
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF
    
    def next_uint32(self) -> int:
        """Xorshift32 算法"""
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17)
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x
    
    def range(self, min_val: int, max_val: int) -> int:
        return min_val + (self.next_uint32() % (max_val - min_val + 1))
    
    def uniform(self) -> float:
        return self.next_uint32() / 0xFFFFFFFF

# 使用方式
class GameWorld:
    def __init__(self, match_seed: int):
        # 比赛级随机
        self.match_rng = DeterministicRNG(match_seed)
        
    def start_frame(self, frame_id: int):
        # 帧级随机（基于帧号，确保所有客户端一致）
        self.frame_rng = DeterministicRNG(frame_id * 12345 + self.match_rng.range(0, 10000))
```

### 最佳实践
- ✅ 比赛开始时同步种子
- ✅ 使用确定性算法（LCG、Xorshift）
- ✅ 分离全局随机和帧随机
- ❌ 不要使用 time.time() 作为种子
- ❌ 不要使用 random 模块

## 5.3 网络抖动与丢包

### 问题描述
网络延迟不稳定，包丢失导致帧不同步。

### 解决方案

```python
class FrameBufferManager:
    """抗抖动帧缓冲"""
    
    def __init__(self, base_buffer: int = 3):
        self.base_buffer = base_buffer
        self.current_buffer = base_buffer
        self.frame_queue = {}  # {frame_id: frame_data}
        self.last_continuous_frame = -1
        
    def add_frame(self, frame_id: int, frame_data):
        """添加收到的帧"""
        self.frame_queue[frame_id] = frame_data
        self._update_continuous_frame()
    
    def _update_continuous_frame(self):
        """更新连续帧标记"""
        while (self.last_continuous_frame + 1) in self.frame_queue:
            self.last_continuous_frame += 1
    
    def get_executable_frame(self, current_time: float) -> Optional[int]:
        """获取可执行的帧"""
        target_frame = self.last_continuous_frame
        
        # 检查缓冲是否充足
        buffered = max(self.frame_queue.keys(), default=0) - target_frame
        
        if buffered < self.current_buffer:
            # 缓冲不足，暂停执行
            return None
        
        return target_frame
    
    def on_timeout(self, frame_id: int):
        """处理超时帧"""
        # 策略1：使用空输入填充
        if frame_id not in self.frame_queue:
            self.frame_queue[frame_id] = self._create_empty_frame(frame_id)
        
        # 策略2：断开超时玩家
        # 策略3：请求重发

class PacketLossHandler:
    """丢包处理"""
    
    def __init__(self, connection):
        self.connection = connection
        self.sent_packets = {}  # {seq: (data, send_time, retries)}
        self.ack_received = set()
    
    async def send_with_retry(self, seq: int, data: bytes, max_retries: int = 3):
        """带重试的发送"""
        self.sent_packets[seq] = [data, time.time(), 0]
        
        for retry in range(max_retries):
            await self.connection.send(data)
            
            await asyncio.sleep(0.1)  # 等待 ACK
            
            if seq in self.ack_received:
                del self.sent_packets[seq]
                return True
            
            self.sent_packets[seq][2] += 1
        
        return False  # 重试失败
```

### 最佳实践
- ✅ 设置合理的帧缓冲（2-4帧）
- ✅ 超时使用上一次输入或空输入
- ✅ 重要消息带序号和重试
- ✅ 监控网络状况动态调整缓冲

## 5.4 客户端预测回滚

### 问题描述
客户端预测错误时需要回滚，频繁回滚影响体验。

### 解决方案

```python
class PredictionRollbackSystem:
    """预测回滚系统"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.predicted_frames = []  # 预测帧历史
        self.state_snapshots = {}   # 状态快照
        self.rollback_count = 0
    
    def predict_frame(self, frame_id: int, my_input: bytes):
        """预测执行"""
        # 保存快照
        self.state_snapshots[frame_id] = self.game_state.serialize()
        
        # 预测其他玩家输入（使用上一帧）
        predicted_inputs = self._predict_other_inputs(frame_id)
        predicted_inputs[self.game_state.player_id] = my_input
        
        # 执行预测
        self.game_state.apply_inputs(predicted_inputs)
        self.predicted_frames.append(frame_id)
    
    def on_server_frame(self, server_frame):
        """服务器帧到达"""
        frame_id = server_frame.frame_id
        
        if frame_id not in self.predicted_frames:
            # 非预测帧，直接执行
            self.game_state.apply_frame(server_frame)
            return
        
        # 比较预测与实际
        predicted_input = self.game_state.get_applied_input(frame_id)
        actual_input = server_frame.inputs
        
        if self._inputs_match(predicted_input, actual_input):
            # 预测正确
            self.predicted_frames.remove(frame_id)
        else:
            # 预测错误，回滚
            self._rollback_and_replay(frame_id, actual_input)
    
    def _rollback_and_replay(self, wrong_frame: int, correct_inputs):
        """回滚并重放"""
        self.rollback_count += 1
        
        # 1. 回滚到错误帧之前
        self.game_state.deserialize(self.state_snapshots[wrong_frame])
        
        # 2. 应用正确的输入
        self.game_state.apply_inputs(correct_inputs)
        
        # 3. 重放后续预测帧
        frames_to_replay = [f for f in self.predicted_frames if f > wrong_frame]
        for frame_id in sorted(frames_to_replay):
            # 更新其他玩家输入为实际值（如果已收到）
            self.game_state.replay_frame(frame_id)
        
        # 4. 清理已处理的预测帧
        self.predicted_frames = [f for f in self.predicted_frames if f > wrong_frame]

# 优化：减少回滚频率
class SmartPredictor:
    """智能预测器 - 减少回滚"""
    
    def __init__(self):
        self.player_patterns = {}  # 分析玩家行为模式
    
    def predict_input(self, player_id: int, frame_id: int) -> bytes:
        """智能预测玩家输入"""
        if player_id not in self.player_patterns:
            # 新玩家，使用上次输入
            return self.get_last_input(player_id)
        
        pattern = self.player_patterns[player_id]
        
        # 检测连续相同输入
        if pattern['last_inputs'].count(pattern['last_inputs'][0]) == len(pattern['last_inputs']):
            return pattern['last_inputs'][0]
        
        # 检测周期性模式
        # ... 更复杂的预测逻辑
        
        return self.get_last_input(player_id)
```

### 最佳实践
- ✅ 定期保存状态快照（减少回滚计算量）
- ✅ 智能预测减少错误率
- ✅ 平滑处理回滚（避免画面跳变）
- ✅ 限制最大回滚帧数

## 5.5 状态哈希校验

### 问题描述
如何及时发现状态不同步？

### 解决方案

```python
import hashlib
import json

class StateHashValidator:
    """状态哈希校验"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.hash_history = {}  # {frame_id: hash}
        self.check_interval = 60  # 每60帧校验一次
    
    def compute_hash(self, frame_id: int) -> str:
        """计算状态哈希"""
        state = self.game_state.get_serializable_state()
        
        # 确定性序列化
        def make_deterministic(obj):
            if isinstance(obj, dict):
                return {k: make_deterministic(v) for k, v in sorted(obj.items())}
            elif isinstance(obj, list):
                return [make_deterministic(x) for x in sorted(obj, key=str)]
            elif isinstance(obj, float):
                # 浮点数转字符串，固定精度
                return f"{obj:.6f}"
            return obj
        
        det_state = make_deterministic(state)
        state_str = json.dumps(det_state, sort_keys=True, separators=(',', ':'))
        
        return hashlib.md5(state_str.encode()).hexdigest()
    
    def record_hash(self, frame_id: int):
        """记录哈希"""
        if frame_id % self.check_interval == 0:
            self.hash_history[frame_id] = self.compute_hash(frame_id)
            
            # 发送给服务器校验
            self._send_to_server(frame_id, self.hash_history[frame_id])
    
    def verify_hash(self, frame_id: int, expected_hash: str) -> bool:
        """验证哈希"""
        if frame_id not in self.hash_history:
            return True  # 没有记录，跳过
        
        actual = self.hash_history[frame_id]
        if actual != expected_hash:
            self._handle_mismatch(frame_id, actual, expected_hash)
            return False
        
        return True
    
    def _handle_mismatch(self, frame_id: int, actual: str, expected: str):
        """处理哈希不匹配"""
        print(f"[DESYNC] Frame {frame_id}: {actual} != {expected}")
        
        # 记录详细状态用于调试
        self._dump_debug_info(frame_id)
        
        # 策略：请求完整状态同步
        self._request_full_sync()

class IncrementalHasher:
    """增量哈希 - 减少计算量"""
    
    def __init__(self):
        self.last_hash = 0
    
    def update(self, entity_id: int, state: dict) -> int:
        """增量更新哈希"""
        entity_hash = hash(frozenset([
            (k, round(v, 6) if isinstance(v, float) else v)
            for k, v in state.items()
        ]))
        
        self.last_hash ^= (entity_id * 31 + entity_hash) & 0xFFFFFFFF
        return self.last_hash
```

### 最佳实践
- ✅ 定期校验（不是每帧，太耗性能）
- ✅ 使用增量哈希减少计算
- ✅ 不匹配时记录详细调试信息
- ✅ 支持请求完整状态同步

## 5.6 断线重连

### 问题描述
玩家断线后重连，如何快速同步？

### 解决方案

```python
class ReconnectionHandler:
    """断线重连处理"""
    
    MAX_DISCONNECT_TIME = 30.0  # 最大断线时间
    
    def __init__(self, server):
        self.server = server
        self.disconnected_players = {}  # {player_id: disconnect_info}
        self.frame_history = []  # 保存最近帧
    
    def on_disconnect(self, player_id: int):
        """玩家断线"""
        self.disconnected_players[player_id] = {
            'disconnect_time': time.time(),
            'last_frame': self.server.current_frame,
            'room_id': self.server.player_rooms.get(player_id)
        }
    
    async def on_reconnect(self, player_id: int, connection) -> bool:
        """玩家重连"""
        if player_id not in self.disconnected_players:
            return False
        
        info = self.disconnected_players[player_id]
        disconnect_duration = time.time() - info['disconnect_time']
        
        if disconnect_duration > self.MAX_DISCONNECT_TIME:
            # 超时太久，无法重连
            return False
        
        # 发送同步数据
        sync_data = await self._prepare_sync_data(player_id, info)
        await connection.send(sync_data)
        
        del self.disconnected_players[player_id]
        return True
    
    async def _prepare_sync_data(self, player_id: int, info: dict) -> bytes:
        """准备同步数据"""
        last_frame = info['last_frame']
        current_frame = self.server.current_frame
        
        # 方案1：发送缺失的帧（适合短时间断线）
        if current_frame - last_frame < 300:  # < 10秒
            missing_frames = self.frame_history[last_frame:current_frame]
            return self._pack_frame_data(missing_frames)
        
        # 方案2：发送完整状态（适合较长时间断线）
        else:
            full_state = self.server.get_full_state()
            return self._pack_state_data(full_state)

class ClientResync:
    """客户端重同步"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.resync_mode = False
    
    def start_resync(self):
        """开始重同步"""
        self.resync_mode = True
        # 暂停游戏逻辑
    
    def apply_resync_data(self, data: bytes):
        """应用同步数据"""
        if self._is_frame_data(data):
            # 快速追帧
            frames = self._unpack_frames(data)
            for frame in frames:
                self.game_state.apply_frame(frame)
        else:
            # 直接设置状态
            state = self._unpack_state(data)
            self.game_state.set_state(state)
        
        self.resync_mode = False
    
    def fast_forward(self, frames: list):
        """快速追帧（不渲染）"""
        for frame in frames:
            self.game_state.apply_frame(frame, render=False)
```

### 最佳实践
- ✅ 服务端保留最近N帧数据
- ✅ 短断线用帧追平，长断线用状态同步
- ✅ 追帧时不渲染，只计算逻辑
- ✅ 设置最大重连时间限制

## 5.7 作弊防范

### 问题描述
帧同步客户端掌握完整逻辑，容易作弊。

### 解决方案

```python
class AntiCheatSystem:
    """反作弊系统"""
    
    def __init__(self, server):
        self.server = server
        self.player_stats = {}
    
    def validate_input(self, player_id: int, input_data: bytes, frame_id: int) -> bool:
        """验证输入合法性"""
        # 1. 输入频率检查
        if not self._check_input_frequency(player_id):
            return False
        
        # 2. 输入范围检查
        if not self._check_input_range(input_data):
            return False
        
        # 3. 物理合理性检查
        if not self._check_physics_validity(player_id, input_data, frame_id):
            return False
        
        return True
    
    def _check_input_frequency(self, player_id: int) -> bool:
        """检查输入频率（防止超级操作）"""
        stats = self.player_stats.get(player_id, {})
        if 'input_times' not in stats:
            stats['input_times'] = []
        
        now = time.time()
        stats['input_times'].append(now)
        
        # 只保留最近1秒
        stats['input_times'] = [t for t in stats['input_times'] if now - t < 1.0]
        
        # 检查APM（假设正常人 < 500 APM）
        if len(stats['input_times']) > 10:  # 每秒10次输入
            return False
        
        return True
    
    def verify_state_hash(self, player_id: int, frame_id: int, claimed_hash: str) -> bool:
        """验证玩家声明的状态哈希"""
        # 服务端计算自己的哈希
        server_hash = self.server.compute_frame_hash(frame_id)
        
        if server_hash != claimed_hash:
            # 记录可疑行为
            self._flag_suspicious(player_id, 'hash_mismatch', frame_id)
            return False
        
        return True
    
    def detect_speed_hack(self, player_id: int) -> bool:
        """检测加速器"""
        stats = self.player_stats.get(player_id, {})
        
        # 检查帧处理速度
        if 'frame_times' in stats:
            avg_time = sum(stats['frame_times'][-10:]) / 10
            expected_time = 33  # 33ms per frame
            
            if avg_time < expected_time * 0.8:  # 快于预期20%
                return True
        
        return False

# 服务端权威模式
class AuthoritativeServer:
    """权威服务器模式"""
    
    def __init__(self):
        self.server_game_state = None  # 服务端维护完整状态
    
    async def process_frame(self):
        """服务端处理帧"""
        # 收集所有玩家输入
        inputs = await self._collect_inputs()
        
        # 服务端执行逻辑
        self.server_game_state.apply_inputs(inputs)
        
        # 计算状态哈希
        state_hash = self.compute_hash()
        
        # 发送结果给客户端
        await self._broadcast_result(inputs, state_hash)
    
    def detect_desync(self, player_reports: dict) -> Optional[int]:
        """检测哪个玩家不同步"""
        # 多数投票
        hash_counts = {}
        for player_id, hash_val in player_reports.items():
            hash_counts[hash_val] = hash_counts.get(hash_val, 0) + 1
        
        majority_hash = max(hash_counts, key=hash_counts.get)
        
        for player_id, hash_val in player_reports.items():
            if hash_val != majority_hash:
                return player_id  # 返回不同步的玩家
        
        return None
```

### 最佳实践
- ✅ 输入合法性校验（频率、范围）
- ✅ 服务端定期计算状态哈希
- ✅ 多数投票检测异常玩家
- ✅ 记录日志用于事后分析
- ❌ 无法完全防止透视等客户端作弊

## 5.8 本章小结

| 问题 | 核心挑战 | 推荐方案 |
|------|----------|----------|
| 浮点精度 | 跨平台一致性 | 定点数运算 |
| 随机同步 | 随机序列一致 | 确定性RNG + 同步种子 |
| 网络抖动 | 延迟不稳定 | 帧缓冲 + 动态调整 |
| 预测回滚 | 预测错误处理 | 状态快照 + 智能预测 |
| 状态校验 | 及时发现不同步 | 定期哈希校验 |
| 断线重连 | 快速恢复同步 | 帧追平 / 状态同步 |
| 作弊防范 | 客户端可信度低 | 服务端验证 + 多数投票 |

---

**下一章**：[生产实践](06-production.md) - 性能优化与容错处理
