"""
确定性物理引擎

本模块提供帧同步所需的确定性物理模拟：
- Entity: 游戏实体，使用定点数坐标
- PhysicsEngine: 物理引擎，处理碰撞和物理模拟
- EntityPool: 实体对象池，优化内存分配
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math


@dataclass
class Entity:
    """
    游戏实体
    
    表示游戏中的一个实体（角色、子弹、道具等）。
    所有坐标和速度使用**定点数**表示，保证跨平台确定性。
    
    定点数格式 (16.16):
        - 使用 32 位整数
        - 高 16 位表示整数部分
        - 低 16 位表示小数部分
        - 精度：约 0.000015
        - 范围：-32768 到 32767
    
    属性:
        entity_id (int): 
            实体的唯一标识符。
            用于在游戏中引用和查找实体。
        
        x (int): 
            X 坐标（定点数 16.16 格式）。
            例如：x = 100 * 65536 = 6553600 表示 x=100.0
        
        y (int): 
            Y 坐标（定点数 16.16 格式）。
        
        vx (int): 
            X 方向速度（定点数）。
            单位：像素/秒。
            例如：vx = 300 * 65536 表示每秒移动 300 像素。
        
        vy (int): 
            Y 方向速度（定点数）。
        
        width (int): 
            实体宽度（定点数）。
            默认 32 像素。
        
        height (int): 
            实体高度（定点数）。
            默认 32 像素。
        
        hp (int): 
            当前生命值。
            范围：0 到 max_hp。
        
        max_hp (int): 
            最大生命值。
            默认 100。
        
        flags (int): 
            状态标志位。
            可用于存储额外状态（是否跳跃、是否无敌等）。
    
    类常量:
        FIXED_SHIFT (16): 定点数小数位数
        FIXED_SCALE (65536): 定点数缩放因子 = 2^16
    """
    entity_id: int
    x: int = 0
    y: int = 0
    vx: int = 0
    vy: int = 0
    width: int = 32 << 16
    height: int = 32 << 16
    hp: int = 100
    max_hp: int = 100
    flags: int = 0
    
    # 定点数配置
    FIXED_SHIFT = 16
    FIXED_SCALE = 1 << FIXED_SHIFT
    
    @classmethod
    def from_float(cls, entity_id: int, x: float, y: float) -> 'Entity':
        """
        从浮点数坐标创建实体
        
        Args:
            entity_id: 实体ID
            x: X 坐标（浮点数，像素）
            y: Y 坐标（浮点数，像素）
        
        Returns:
            Entity 实例
        
        示例:
            entity = Entity.from_float(1, 100.5, 200.0)
        """
        return cls(
            entity_id=entity_id,
            x=int(x * cls.FIXED_SCALE),
            y=int(y * cls.FIXED_SCALE)
        )
    
    def to_float(self) -> Tuple[float, float]:
        """
        转换为浮点数坐标
        
        Returns:
            (x, y) 元组，浮点数像素坐标
        
        示例:
            x, y = entity.to_float()  # (100.5, 200.0)
        """
        return (self.x / self.FIXED_SCALE, self.y / self.FIXED_SCALE)
    
    def to_int(self) -> Tuple[int, int]:
        """
        转换为整数像素坐标
        
        小数部分被截断。
        
        Returns:
            (x, y) 元组，整数像素坐标
        """
        return (self.x >> self.FIXED_SHIFT, self.y >> self.FIXED_SHIFT)
    
    def update_position(self, dt_ms: int):
        """
        根据速度更新位置
        
        使用整数运算保证确定性。
        公式：position += velocity * dt / 1000
        
        Args:
            dt_ms: 时间增量（毫秒）
        """
        if dt_ms <= 0:
            return
        self.x += (self.vx * dt_ms) // 1000
        self.y += (self.vy * dt_ms) // 1000
    
    def set_velocity(self, vx: float, vy: float):
        """
        设置速度（浮点输入）
        
        Args:
            vx: X 方向速度（像素/秒）
            vy: Y 方向速度（像素/秒）
        """
        self.vx = int(vx * self.FIXED_SCALE)
        self.vy = int(vy * self.FIXED_SCALE)
    
    def get_bounds(self) -> Tuple[int, int, int, int]:
        """
        获取碰撞边界
        
        Returns:
            (x1, y1, x2, y2) 元组，定点数坐标
        """
        return (
            self.x,
            self.y,
            self.x + self.width,
            self.y + self.height
        )
    
    def reset(self):
        """重置实体状态（用于对象池）"""
        self.x = 0
        self.y = 0
        self.vx = 0
        self.vy = 0
        self.hp = self.max_hp
        self.flags = 0
    
    def serialize(self) -> dict:
        """
        序列化为字典
        
        Returns:
            包含实体属性的字典
        """
        return {
            'id': self.entity_id,
            'x': self.x,
            'y': self.y,
            'vx': self.vx,
            'vy': self.vy,
            'hp': self.hp,
            'flags': self.flags
        }
    
    @classmethod
    def deserialize(cls, data: dict) -> 'Entity':
        """
        从字典反序列化
        
        Args:
            data: 序列化的数据
        
        Returns:
            Entity 实例
        """
        return cls(
            entity_id=data['id'],
            x=data['x'],
            y=data['y'],
            vx=data.get('vx', 0),
            vy=data.get('vy', 0),
            hp=data.get('hp', 100),
            flags=data.get('flags', 0)
        )


class PhysicsEngine:
    """
    确定性物理引擎
    
    处理游戏中所有实体的物理模拟：
    - 重力
    - 摩擦力
    - 碰撞检测和响应
    - 边界处理
    
    所有计算使用整数/定点数，保证跨平台确定性。
    
    类常量:
        GRAVITY (int): 
            重力加速度（定点数）。
            默认 980 像素/秒²。
            值 = 980 * 65536 = 64174080
        
        FRICTION (int): 
            摩擦系数（定点数）。
            默认 0.9。
            值 = 0.9 * 65536 = 58982
        
        MAX_VELOCITY (int): 
            最大速度限制（定点数）。
            默认 1000 像素/秒。
        
        WORLD_WIDTH (int): 
            游戏世界宽度（定点数）。
            默认 1920 像素。
        
        WORLD_HEIGHT (int): 
            游戏世界高度（定点数）。
            默认 1080 像素。
    
    属性:
        entities (Dict[int, Entity]): 
            所有实体的字典。
            键为 entity_id。
        
        collision_pairs (List[Tuple[int, int]]): 
            当前帧检测到的碰撞对。
            每个元素是 (entity_id1, entity_id2)。
        
        spatial_grid (Dict[Tuple[int, int], List[int]]): 
            空间划分网格（性能优化）。
            键为网格坐标 (cx, cy)，值为该网格内的实体ID列表。
        
        cell_size (int): 
            网格单元大小（定点数）。
            默认 64 像素。
    """
    
    GRAVITY = 980 << 16
    FRICTION = 58982
    MAX_VELOCITY = 1000 << 16
    WORLD_WIDTH = 1920 << 16
    WORLD_HEIGHT = 1080 << 16
    
    def __init__(self):
        """初始化物理引擎"""
        self.entities: Dict[int, Entity] = {}
        self.collision_pairs: List[Tuple[int, int]] = []
        self.spatial_grid: Dict[Tuple[int, int], List[int]] = {}
        self.cell_size = 64 << 16
    
    def add_entity(self, entity: Entity):
        """
        添加实体到物理引擎
        
        Args:
            entity: 要添加的实体
        """
        self.entities[entity.entity_id] = entity
    
    def remove_entity(self, entity_id: int):
        """
        移除实体
        
        Args:
            entity_id: 要移除的实体ID
        """
        if entity_id in self.entities:
            del self.entities[entity_id]
    
    def get_entity(self, entity_id: int) -> Optional[Entity]:
        """
        获取实体
        
        Args:
            entity_id: 实体ID
        
        Returns:
            Entity 对象，不存在则返回 None
        """
        return self.entities.get(entity_id)
    
    def update(self, dt_ms: int):
        """
        更新物理模拟
        
        每帧调用一次，更新所有实体的物理状态。
        
        流程:
        1. 应用重力
        2. 限制最大速度
        3. 更新位置
        4. 应用摩擦力
        5. 处理边界碰撞
        6. 处理实体间碰撞
        
        Args:
            dt_ms: 时间增量（毫秒），通常为 33 (30fps)
        """
        if dt_ms <= 0:
            return
            
        for entity in self.entities.values():
            # 应用重力
            entity.vy += (self.GRAVITY * dt_ms) // 1000
            
            # 限制最大速度
            entity.vx = max(-self.MAX_VELOCITY, min(self.MAX_VELOCITY, entity.vx))
            entity.vy = max(-self.MAX_VELOCITY, min(self.MAX_VELOCITY, entity.vy))
            
            # 更新位置
            entity.update_position(dt_ms)
            
            # 应用摩擦力
            entity.vx = (entity.vx * self.FRICTION) >> 16
        
        # 边界碰撞
        self._handle_boundary_collision()
        
        # 实体间碰撞
        self._handle_entity_collision_optimized()
    
    def _handle_boundary_collision(self):
        """处理边界碰撞"""
        for entity in self.entities.values():
            if entity.x < 0:
                entity.x = 0
                entity.vx = 0
            
            if entity.x + entity.width > self.WORLD_WIDTH:
                entity.x = self.WORLD_WIDTH - entity.width
                entity.vx = 0
            
            if entity.y < 0:
                entity.y = 0
                entity.vy = 0
            
            if entity.y + entity.height > self.WORLD_HEIGHT:
                entity.y = self.WORLD_HEIGHT - entity.height
                entity.vy = 0
    
    def _update_spatial_grid(self):
        """更新空间网格"""
        self.spatial_grid.clear()
        for eid, entity in self.entities.items():
            cx = (entity.x + entity.width // 2) // self.cell_size
            cy = (entity.y + entity.height // 2) // self.cell_size
            cell = (cx, cy)
            if cell not in self.spatial_grid:
                self.spatial_grid[cell] = []
            self.spatial_grid[cell].append(eid)
    
    def _handle_entity_collision_optimized(self):
        """优化的实体间碰撞检测（空间网格）"""
        self.collision_pairs.clear()
        self._update_spatial_grid()
        
        checked = set()
        
        for cell, entity_ids in self.spatial_grid.items():
            # 检查同单元格内的实体
            for i, eid1 in enumerate(entity_ids):
                for eid2 in entity_ids[i+1:]:
                    pair = (min(eid1, eid2), max(eid1, eid2))
                    if pair in checked:
                        continue
                    checked.add(pair)
                    
                    e1 = self.entities[eid1]
                    e2 = self.entities[eid2]
                    if self._check_aabb_collision(e1, e2):
                        self.collision_pairs.append(pair)
                        self._resolve_collision(e1, e2)
            
            # 检查相邻单元格
            cx, cy = cell
            neighbors = [(-1,0), (0,-1), (-1,-1), (1,-1)]
            
            for dx, dy in neighbors:
                neighbor = (cx + dx, cy + dy)
                if neighbor not in self.spatial_grid:
                    continue
                    
                for eid1 in entity_ids:
                    for eid2 in self.spatial_grid[neighbor]:
                        pair = (min(eid1, eid2), max(eid1, eid2))
                        if pair in checked:
                            continue
                        checked.add(pair)
                        
                        e1 = self.entities[eid1]
                        e2 = self.entities[eid2]
                        if self._check_aabb_collision(e1, e2):
                            self.collision_pairs.append(pair)
                            self._resolve_collision(e1, e2)
    
    def _check_aabb_collision(self, a: Entity, b: Entity) -> bool:
        """
        AABB 碰撞检测
        
        Args:
            a: 实体A
            b: 实体B
        
        Returns:
            True 如果两个实体碰撞
        """
        return (a.x < b.x + b.width and
                a.x + a.width > b.x and
                a.y < b.y + b.height and
                a.y + a.height > b.y)
    
    def _resolve_collision(self, a: Entity, b: Entity):
        """
        解决碰撞（分离实体）
        
        Args:
            a: 实体A
            b: 实体B
        """
        overlap_x = min(a.x + a.width - b.x, b.x + b.width - a.x)
        overlap_y = min(a.y + a.height - b.y, b.y + b.height - a.y)
        
        if overlap_x < overlap_y:
            if a.x < b.x:
                a.x -= overlap_x // 2
                b.x += overlap_x // 2
            else:
                a.x += overlap_x // 2
                b.x -= overlap_x // 2
            a.vx = 0
            b.vx = 0
        else:
            if a.y < b.y:
                a.y -= overlap_y // 2
                b.y += overlap_y // 2
            else:
                a.y += overlap_y // 2
                b.y -= overlap_y // 2
            a.vy = 0
            b.vy = 0
    
    def apply_input(self, entity_id: int, input_flags: int, speed: int = 300 << 16):
        """
        应用玩家输入到实体
        
        根据输入标志设置实体的移动速度。
        
        Args:
            entity_id: 实体ID
            input_flags: 输入标志位（InputFlags 组合）
            speed: 移动速度（定点数）
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return
        
        from .input import InputFlags
        
        vx = 0
        vy = 0
        
        if input_flags & InputFlags.MOVE_LEFT:
            vx -= speed
        if input_flags & InputFlags.MOVE_RIGHT:
            vx += speed
        if input_flags & InputFlags.MOVE_UP:
            vy -= speed
        if input_flags & InputFlags.MOVE_DOWN:
            vy += speed
        
        entity.vx = vx
        entity.vy = vy
    
    def serialize_state(self) -> dict:
        """
        序列化当前物理状态
        
        Returns:
            包含所有实体和碰撞对的字典
        """
        return {
            'entities': {
                eid: entity.serialize() 
                for eid, entity in self.entities.items()
            },
            'collisions': self.collision_pairs.copy()
        }
    
    def deserialize_state(self, state: dict):
        """
        反序列化物理状态
        
        Args:
            state: 序列化的状态数据
        """
        self.entities.clear()
        for eid, data in state.get('entities', {}).items():
            self.entities[int(eid)] = Entity.deserialize(data)


def distance_squared(a: Entity, b: Entity) -> int:
    """
    计算两实体间距离的平方（定点数）
    
    Args:
        a: 实体A
        b: 实体B
    
    Returns:
        距离的平方（定点数）
    """
    dx = a.x - b.x
    dy = a.y - b.y
    return (dx * dx + dy * dy) >> Entity.FIXED_SHIFT


def distance(a: Entity, b: Entity) -> int:
    """
    计算两实体间距离（定点数）
    
    Args:
        a: 实体A
        b: 实体B
    
    Returns:
        距离（定点数）
    """
    dist_sq = distance_squared(a, b)
    return isqrt(dist_sq)


def isqrt(n: int) -> int:
    """
    整数平方根（牛顿法）
    
    确定性的平方根计算，不使用浮点数。
    
    Args:
        n: 非负整数
    
    Returns:
        整数平方根
    """
    if n < 0:
        return 0
    if n == 0:
        return 0
    
    x = n
    y = (x + 1) // 2
    while y < x:
        x = y
        y = (x + n // x) // 2
    
    return x


class EntityPool:
    """
    实体对象池
    
    复用 Entity 对象以减少内存分配和垃圾回收。
    对于需要频繁创建/销毁实体的场景很有用。
    
    属性:
        _pool (List[Entity]): 
            可用的实体池。
            从池中取出使用，用完归还。
        
        _active (set): 
            当前活跃的实体ID集合。
            用于防止重复获取。
    """
    
    def __init__(self, initial_size: int = 100):
        """
        初始化对象池
        
        Args:
            initial_size: 初始池大小
        """
        self._pool: List[Entity] = []
        self._active: set = set()
        
        for i in range(initial_size):
            entity = Entity(entity_id=i)
            self._pool.append(entity)
    
    def acquire(self, entity_id: int) -> Entity:
        """
        从池中获取实体
        
        Args:
            entity_id: 要分配的实体ID
        
        Returns:
            Entity 实例
        
        Raises:
            ValueError: 如果实体ID已在使用中
        """
        if entity_id in self._active:
            raise ValueError(f"Entity {entity_id} already active")
        
        if self._pool:
            entity = self._pool.pop()
            entity.entity_id = entity_id
            entity.reset()
            self._active.add(entity_id)
            return entity
        
        entity = Entity(entity_id=entity_id)
        self._active.add(entity_id)
        return entity
    
    def release(self, entity: Entity):
        """
        将实体归还到池中
        
        Args:
            entity: 要归还的实体
        """
        if entity.entity_id in self._active:
            self._active.remove(entity.entity_id)
            self._pool.append(entity)
