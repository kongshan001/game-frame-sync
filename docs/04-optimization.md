# 第四章：延迟优化

## 4.1 延迟的来源

```
总延迟 = 输入延迟 + 网络延迟 + 处理延迟 + 显示延迟

输入延迟：控制器采样到应用（1-16ms）
网络延迟：RTT / 2（20-100ms）
处理延迟：帧缓冲 + 计算时间（33-100ms）
显示延迟：渲染 + 显示器刷新（8-33ms）

典型 FPS 游戏：100-250ms
优化后帧同步：50-150ms
```

## 4.2 客户端预测（Client-Side Prediction）

### 4.2.1 核心思想

> 不等待服务器确认，本地立即执行输入，稍后用服务器状态校验

```
传统帧同步：
Client 发送输入 ────(等待)────▶ Server
Client ◀─────── 收到确认 ─────── Server
Client 执行逻辑
总延迟 = RTT + 帧缓冲

客户端预测：
Client 发送输入 ────(等待)────▶ Server
Client 立即执行预测 ◀─────── 收到确认 ─────── Server
总延迟 ≈ 0（如果预测正确）
```

### 4.2.2 预测实现

```python
class ClientPredictor:
    """客户端预测器"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.predicted_frames = {}  # 预测的帧
        self.unconfirmed_inputs = []  # 未确认的输入
    
    def predict(self, frame_id: int, player_input: bytes) -> GameFrame:
        """预测一帧"""
        # 保存未确认输入
        self.unconfirmed_inputs.append((frame_id, player_input))
        
        # 创建预测帧
        predicted = GameFrame(
            frame_id=frame_id,
            inputs={
                self.game_state.player_id: player_input
            },
            confirmed=False
        )
        
        # 应用预测（假设其他玩家输入不变）
        for other_id in self.game_state.other_players:
            # 使用上一帧的输入作为预测
            last_input = self.game_state.get_last_input(other_id)
            predicted.inputs[other_id] = last_input
        
        self.predicted_frames[frame_id] = predicted
        
        # 立即执行预测帧
        self.game_state.apply_frame(predicted)
        
        return predicted
    
    def on_server_frame(self, server_frame: GameFrame):
        """收到服务器帧，校验预测"""
        frame_id = server_frame.frame_id
        
        if frame_id in self.predicted_frames:
            predicted = self.predicted_frames[frame_id]
            
            if self._frames_match(predicted, server_frame):
                # 预测正确，无需处理
                del self.predicted_frames[frame_id]
            else:
                # 预测错误，需要回滚
                self._rollback_and_replay(frame_id, server_frame)
        
        # 清理已确认的输入
        self.unconfirmed_inputs = [
            (f, i) for f, i in self.unconfirmed_inputs
            if f > frame_id
        ]
    
    def _frames_match(self, predicted: GameFrame, server: GameFrame) -> bool:
        """比较预测帧和服务器帧"""
        for player_id in server.inputs:
            pred_input = predicted.inputs.get(player_id)
            serv_input = server.inputs.get(player_id)
            if pred_input != serv_input:
                return False
        return True
    
    def _rollback_and_replay(self, frame_id: int, server_frame: GameFrame):
        """回滚并重放"""
        # 1. 回滚到分歧点之前
        self.game_state.rollback_to(frame_id - 1)
        
        # 2. 应用服务器帧
        self.game_state.apply_frame(server_frame)
        
        # 3. 重放后续预测帧（使用正确的服务器输入）
        for f, _ in self.unconfirmed_inputs:
            if f > frame_id and f in self.predicted_frames:
                # 更新预测帧中的其他玩家输入
                # 重新应用
                self.game_state.apply_frame(self.predicted_frames[f])
```

### 4.2.3 状态快照与回滚

```python
class StateSnapshot:
    """状态快照管理"""
    
    MAX_SNAPSHOTS = 60  # 保留最近60帧快照
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.snapshots = {}  # {frame_id: snapshot_data}
    
    def save(self, frame_id: int):
        """保存快照"""
        snapshot = self.game_state.serialize()
        self.snapshots[frame_id] = snapshot
        
        # 清理旧快照
        oldest = frame_id - self.MAX_SNAPSHOTS
        for f in list(self.snapshots.keys()):
            if f < oldest:
                del self.snapshots[f]
    
    def restore(self, frame_id: int) -> bool:
        """恢复快照"""
        if frame_id not in self.snapshots:
            return False
        
        self.game_state.deserialize(self.snapshots[frame_id])
        return True
```

## 4.3 插值渲染

### 4.3.1 为什么需要插值？

```
逻辑帧：30fps，固定 33ms
渲染帧：60fps，可变 16.6ms

如果不插值：
逻辑帧 1 ─────────── 逻辑帧 2 ─────────── 逻辑帧 3
   │                     │                     │
   ▼                     ▼                     ▼
渲染1  渲染2   渲染3   渲染4   渲染5   渲染6
  (卡顿，位置突变)

使用插值：
渲染2 = lerp(帧1, 帧2, 0.5)  # 平滑过渡
```

### 4.3.2 插值实现

```python
class InterpolatedRenderer:
    """插值渲染器"""
    
    def __init__(self, game_state):
        self.game_state = game_state
        self.prev_state = None
        self.current_state = None
        self.render_alpha = 0.0  # 插值因子 [0, 1]
    
    def update(self, dt: float, frame_time: float):
        """更新插值因子"""
        self.render_alpha = dt / frame_time
        self.render_alpha = max(0.0, min(1.0, self.render_alpha))
    
    def on_logic_frame(self):
        """逻辑帧更新时"""
        self.prev_state = self.current_state
        self.current_state = self.game_state.copy()
        self.render_alpha = 0.0
    
    def render(self, screen):
        """插值渲染"""
        for entity_id in self.current_state.entities:
            prev_entity = self.prev_state.get_entity(entity_id)
            curr_entity = self.current_state.get_entity(entity_id)
            
            if prev_entity:
                # 插值位置
                x = self._lerp(prev_entity.x, curr_entity.x, self.render_alpha)
                y = self._lerp(prev_entity.y, curr_entity.y, self.render_alpha)
                rotation = self._lerp_angle(prev_entity.rotation, curr_entity.rotation, self.render_alpha)
            else:
                x, y, rotation = curr_entity.x, curr_entity.y, curr_entity.rotation
            
            self._draw_entity(screen, x, y, rotation, curr_entity)
    
    def _lerp(self, a: float, b: float, t: float) -> float:
        """线性插值"""
        return a + (b - a) * t
    
    def _lerp_angle(self, a: float, b: float, t: float) -> float:
        """角度插值（最短路径）"""
        diff = b - a
        while diff > 180: diff -= 360
        while diff < -180: diff += 360
        return a + diff * t
```

## 4.4 延迟补偿

### 4.4.1 服务器端延迟补偿

```python
class LagCompensator:
    """服务器延迟补偿"""
    
    def __init__(self):
        self.player_states = {}  # {player_id: {frame: state}}
        self.player_pings = {}   # {player_id: ping_ms}
    
    def save_player_state(self, player_id: int, frame_id: int, state: dict):
        """保存玩家历史状态"""
        if player_id not in self.player_states:
            self.player_states[player_id] = {}
        
        self.player_states[player_id][frame_id] = {
            'position': state['position'],
            'timestamp': time.time()
        }
        
        # 只保留最近1秒的状态
        cutoff_frame = frame_id - 30
        for f in list(self.player_states[player_id].keys()):
            if f < cutoff_frame:
                del self.player_states[player_id][f]
    
    def get_historical_state(self, player_id: int, frame_id: int) -> Optional[dict]:
        """获取历史状态"""
        if player_id not in self.player_states:
            return None
        return self.player_states[player_id].get(frame_id)
    
    def compensate_for_player(self, player_id: int, action_frame: int, target_id: int) -> Optional[dict]:
        """
        为玩家进行延迟补偿
        
        场景：玩家A在帧100开枪，但他的ping是100ms（3帧）
        我们需要回退目标B到帧97的状态来判断命中
        """
        ping_ms = self.player_pings.get(player_id, 0)
        frame_delay = ping_ms // 33  # 转换为帧数
        
        target_frame = action_frame - frame_delay
        
        return self.get_historical_state(target_id, target_frame)
```

## 4.5 网络优化技巧

### 4.5.1 带宽优化

```python
class InputCompressor:
    """输入压缩"""
    
    @staticmethod
    def compress_inputs(inputs: dict) -> bytes:
        """压缩输入数据"""
        # 假设每个玩家输入最多8字节
        # 使用位打包
        result = bytearray()
        
        for player_id, input_data in sorted(inputs.items()):
            # player_id (1 byte) + input (variable)
            result.append(player_id)
            result.extend(input_data)
        
        # 使用 zlib 进一步压缩
        import zlib
        return zlib.compress(bytes(result), level=1)  # level 1 for speed
    
    @staticmethod
    def decompress_inputs(data: bytes) -> dict:
        """解压输入数据"""
        import zlib
        decompressed = zlib.decompress(data)
        
        inputs = {}
        i = 0
        while i < len(decompressed):
            player_id = decompressed[i]
            input_len = 8  # 假设固定长度
            input_data = decompressed[i+1:i+1+input_len]
            inputs[player_id] = bytes(input_data)
            i += 1 + input_len
        
        return inputs
```

### 4.5.2 批量发送

```python
class BatchSender:
    """批量消息发送"""
    
    BATCH_INTERVAL = 0.016  # 16ms
    MAX_BATCH_SIZE = 10
    
    def __init__(self, connection):
        self.connection = connection
        self.pending_messages = []
        self.last_send_time = 0
    
    async def add_message(self, msg_type: MessageType, payload: bytes):
        """添加消息到批次"""
        self.pending_messages.append((msg_type, payload))
        
        # 检查是否应该发送
        now = time.time()
        if (len(self.pending_messages) >= self.MAX_BATCH_SIZE or
            now - self.last_send_time >= self.BATCH_INTERVAL):
            await self._send_batch()
    
    async def _send_batch(self):
        """发送批次"""
        if not self.pending_messages:
            return
        
        # 打包所有消息
        batch = msgpack.packb([
            {'t': m[0], 'p': m[1]}
            for m in self.pending_messages
        ])
        
        await self.connection.send_raw(batch)
        self.pending_messages = []
        self.last_send_time = time.time()
```

## 4.6 性能监控

```python
class PerformanceMonitor:
    """性能监控"""
    
    def __init__(self):
        self.metrics = {
            'frame_time': [],
            'network_rtt': [],
            'prediction_accuracy': [],
            'rollback_count': 0
        }
    
    def record_frame_time(self, frame_time_ms: float):
        """记录帧时间"""
        self.metrics['frame_time'].append(frame_time_ms)
        if len(self.metrics['frame_time']) > 100:
            self.metrics['frame_time'].pop(0)
    
    def record_prediction_result(self, correct: bool):
        """记录预测结果"""
        self.metrics['prediction_accuracy'].append(1 if correct else 0)
        if len(self.metrics['prediction_accuracy']) > 100:
            self.metrics['prediction_accuracy'].pop(0)
    
    def get_stats(self) -> dict:
        """获取统计数据"""
        frame_times = self.metrics['frame_time']
        predictions = self.metrics['prediction_accuracy']
        
        return {
            'avg_frame_time': sum(frame_times) / len(frame_times) if frame_times else 0,
            'max_frame_time': max(frame_times) if frame_times else 0,
            'prediction_accuracy': sum(predictions) / len(predictions) * 100 if predictions else 0,
            'rollback_count': self.metrics['rollback_count']
        }
```

## 4.7 本章小结

- 客户端预测消除输入延迟，但需要回滚机制
- 插值渲染让画面平滑，分离逻辑帧和渲染帧
- 延迟补偿在服务器端回退时间，保证公平性
- 带宽优化、批量发送减少网络压力
- 性能监控帮助发现问题

---

**下一章**：[技术卡点](05-challenges.md) - 常见问题与解决方案
