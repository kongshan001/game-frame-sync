# 第二章：确定性模拟

## 2.1 为什么确定性如此重要？

帧同步的基石是**确定性**：所有客户端在相同输入下必须产生完全相同的状态。任何微小的差异都会随时间放大，导致游戏状态彻底分叉。

```
帧 1: 差异 0.0001（浮点误差）
帧 100: 差异 0.01
帧 1000: 差异 1.0（可见偏差）
帧 10000: 差异 100.0（状态完全不同）
```

## 2.2 确定性的敌人

### 2.2.1 浮点数不一致

**问题**：
- 不同 CPU 架构的浮点运算结果可能不同
- 编译器优化可能改变运算顺序
- x87 FPU vs SSE 的精度不同

```python
# ❌ 危险：浮点数不确定
def bad_collision(a, b):
    return a.x < b.x + b.width  # 浮点比较

# ✅ 安全：定点数
FIXED_SCALE = 10000  # 精度因子

def fixed_mul(a, b):
    """定点数乘法"""
    return (a * b) // FIXED_SCALE

def fixed_div(a, b):
    """定点数除法"""
    return (a * FIXED_SCALE) // b
```

**解决方案**：

1. **使用定点数**
   ```python
   class FixedPoint:
       """32位定点数，16.16格式"""
       SCALE = 65536
       
       def __init__(self, value=0):
           if isinstance(value, float):
               self.raw = int(value * self.SCALE)
           else:
               self.raw = value
       
       def __add__(self, other):
           return FixedPoint(self.raw + other.raw)
       
       def __mul__(self, other):
           # (a * b) >> 16
           return FixedPoint((self.raw * other.raw) >> 16)
       
       def to_float(self):
           return self.raw / self.SCALE
   ```

2. **限制浮点范围**
   ```python
   import struct
   
   def deterministic_float(f):
       """将浮点数截断到32位，保证跨平台一致"""
       return struct.unpack('f', struct.pack('f', f))[0]
   ```

3. **禁用编译器浮点优化**（C/C++）
   ```bash
   # GCC/Clang
   -ffloat-store -fexcess-precision=standard
   ```

### 2.2.2 随机数不同步

**问题**：每个客户端的随机数序列不同

```python
# ❌ 每个客户端随机数不同
import random
damage = random.randint(10, 20)

# ❌ 时间相关的随机
seed = time.time()  # 每台机器时间不同
```

**解决方案**：

1. **同步随机种子**
   ```python
   class DeterministicRNG:
       """确定性随机数生成器"""
       
       def __init__(self, seed):
           self.state = seed
       
       def next(self):
           """线性同余生成器（LCG）"""
           # 参数来自 Numerical Recipes
           self.state = (self.state * 1664525 + 1013904223) & 0xFFFFFFFF
           return self.state
       
       def range(self, min_val, max_val):
           """返回 [min_val, max_val] 范围的整数"""
           return min_val + (self.next() % (max_val - min_val + 1))
       
       def uniform(self):
           """返回 [0, 1) 范围的浮点数"""
           return self.next() / 0xFFFFFFFF
   
   # 使用
   rng = DeterministicRNG(game_seed)  # 所有客户端用相同种子
   damage = rng.range(10, 20)  # 所有客户端得到相同结果
   ```

2. **帧同步随机种子**
   ```python
   # 每帧的随机种子基于帧号
   frame_rng = DeterministicRNG(frame_number * 12345)
   ```

### 2.2.3 遍历顺序不一致

**问题**：字典/哈希表遍历顺序不确定

```python
# ❌ 字典遍历顺序不确定
units = {'a': unit1, 'b': unit2, 'c': unit3}
for name, unit in units.items():  # 顺序可能不同！
    unit.update()
```

**解决方案**：

```python
# ✅ 按固定顺序遍历
for name in sorted(units.keys()):  # 字母序
    units[name].update()

# ✅ 使用有序数据结构
from collections import OrderedDict
units = OrderedDict([('a', unit1), ('b', unit2), ('c', unit3)])

# ✅ 按 ID 遍历
unit_ids = sorted(units.keys(), key=lambda x: x.id)
for uid in unit_ids:
    units[uid].update()
```

### 2.2.4 时间相关的不确定

**问题**：使用系统时间导致不确定

```python
# ❌ 使用真实时间
dt = time.time() - last_time

# ❌ 依赖系统时间的逻辑
if time.time() > spawn_time:
    spawn_enemy()
```

**解决方案**：

```python
# ✅ 使用游戏帧时间
game_time = frame_number * FRAME_TIME

# ✅ 固定时间步长
dt = FIXED_FRAME_TIME  # 固定 33ms
```

### 2.2.5 多线程竞争

**问题**：多线程执行顺序不确定

```python
# ❌ 多线程更新
with ThreadPool(4) as pool:
    pool.map(update_unit, units)  # 顺序不确定！
```

**解决方案**：

```python
# ✅ 单线程执行游戏逻辑
for unit in units:
    update_unit(unit)

# ✅ 如果必须多线程，使用确定性任务分配
def deterministic_parallel_update(units, num_threads=4):
    """确定性并行更新"""
    chunks = [units[i::num_threads] for i in range(num_threads)]
    # 每个 chunk 的执行是独立的，且分配是确定性的
    for chunk in chunks:
        for unit in chunk:
            update_unit(unit)
```

## 2.3 确定性物理引擎

### 2.3.1 简单物理模拟

```python
class DeterministicPhysics:
    """确定性2D物理"""
    
    GRAVITY = 980  # 像素/秒²（整数）
    
    def __init__(self):
        self.objects = []
    
    def update(self, dt_ms):
        """更新一帧物理"""
        dt = dt_ms  # 使用整数毫秒
        
        for obj in self.objects:
            # 应用重力（整数运算）
            obj.vy += self.GRAVITY * dt // 1000
            
            # 更新位置
            obj.x += obj.vx * dt // 1000
            obj.y += obj.vy * dt // 1000
            
            # 碰撞检测（整数）
            self._check_collision(obj)
    
    def _check_collision(self, obj):
        """AABB碰撞检测"""
        if obj.y + obj.height > 600:  # 地面
            obj.y = 600 - obj.height
            obj.vy = 0
```

### 2.3.2 碰撞检测顺序

```python
# ✅ 确定性碰撞检测：按ID排序
def detect_collisions(objects):
    """确定性碰撞检测"""
    n = len(objects)
    
    # 按 ID 排序，保证检测顺序一致
    sorted_objects = sorted(objects, key=lambda o: o.id)
    
    for i in range(n):
        for j in range(i + 1, n):
            if check_aabb(sorted_objects[i], sorted_objects[j]):
                resolve_collision(sorted_objects[i], sorted_objects[j])
```

## 2.4 状态校验

### 2.4.1 状态哈希

定期计算状态哈希，用于检测不同步：

```python
import hashlib
import json

def compute_state_hash(game_state):
    """计算游戏状态的确定性哈希"""
    # 将状态序列化为确定性格式
    state_dict = {
        'frame': game_state.frame,
        'units': sorted([  # 排序保证顺序
            {'id': u.id, 'x': u.x, 'y': u.y, 'hp': u.hp}
            for u in game_state.units
        ], key=lambda x: x['id'])
    }
    
    # JSON序列化（sort_keys保证键顺序）
    state_json = json.dumps(state_dict, sort_keys=True, separators=(',', ':'))
    
    # 计算哈希
    return hashlib.md5(state_json.encode()).hexdigest()

# 定期校验
if frame % 60 == 0:  # 每60帧校验一次
    current_hash = compute_state_hash(game)
    # 与其他客户端或服务器校验
    verify_hash(current_hash)
```

### 2.4.2 断点调试

```python
class DeterministicDebugger:
    """确定性调试器"""
    
    def __init__(self):
        self.history = []
    
    def record(self, frame, action, data):
        """记录操作"""
        self.history.append({
            'frame': frame,
            'action': action,
            'data': data,
            'hash': compute_state_hash(game_state)
        })
    
    def compare(self, other_history):
        """对比两个历史，找出分歧点"""
        for i, (h1, h2) in enumerate(zip(self.history, other_history)):
            if h1['hash'] != h2['hash']:
                return i  # 返回分歧帧
        return None
```

## 2.5 浮点数到定点数的转换

### 2.5.1 位置表示

```python
class Position:
    """定点数位置（16.16格式）"""
    
    BITS = 16  # 小数位数
    SCALE = 1 << BITS  # 65536
    
    def __init__(self, x=0, y=0):
        if isinstance(x, float):
            self.x = int(x * self.SCALE)
            self.y = int(y * self.SCALE)
        else:
            self.x = x
            self.y = y
    
    def __add__(self, other):
        return Position(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other):
        return Position(self.x - other.x, self.y - other.y)
    
    def distance_to(self, other):
        """计算距离（定点数）"""
        dx = self.x - other.x
        dy = self.y - other.y
        # 使用整数平方根近似
        dist_sq = (dx * dx + dy * dy) >> self.BITS
        return isqrt(dist_sq)
    
    def to_float(self):
        """转换为浮点数（用于渲染）"""
        return (self.x / self.SCALE, self.y / self.SCALE)
    
    def to_int(self):
        """转换为整数（像素坐标）"""
        return (self.x >> self.BITS, self.y >> self.BITS)
```

## 2.6 常见陷阱总结

| 问题 | 错误做法 | 正确做法 |
|------|----------|----------|
| 浮点数 | 直接使用 float | 使用定点数或截断精度 |
| 随机数 | random 模块 | 同步种子的确定性RNG |
| 遍历 | dict.items() | sorted() 或 OrderedDict |
| 时间 | time.time() | 帧数 * 固定帧时长 |
| 线程 | 多线程更新 | 单线程或确定性分配 |
| 物理 | 物理引擎默认行为 | 自实现确定性物理 |
| 序列化 | pickle（不确定） | JSON + sort_keys |

## 2.7 本章小结

- 确定性是帧同步的生命线
- 浮点数、随机数、遍历顺序、时间、多线程都是潜在的确定性杀手
- 使用定点数、确定性RNG、有序遍历、固定时间步长来保证确定性
- 定期状态哈希校验，及时发现不同步

---

**下一章**：[网络架构](03-network.md) - 设计高效的网络通信协议
