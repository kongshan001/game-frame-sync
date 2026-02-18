"""
Deterministic physics engine for frame synchronization
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math


@dataclass
class Entity:
    """
    游戏实体
    使用整数坐标保证确定性
    """
    entity_id: int
    x: int = 0  # 定点数坐标 (16.16格式)
    y: int = 0
    vx: int = 0  # 速度 (定点数)
    vy: int = 0
    width: int = 32 << 16  # 宽度 (定点数)
    height: int = 32 << 16  # 高度 (定点数)
    hp: int = 100
    max_hp: int = 100
    flags: int = 0  # 状态标志
    
    # 定点数配置
    FIXED_SHIFT = 16
    FIXED_SCALE = 1 << FIXED_SHIFT
    
    @classmethod
    def from_float(cls, entity_id: int, x: float, y: float) -> 'Entity':
        """从浮点数创建实体"""
        return cls(
            entity_id=entity_id,
            x=int(x * cls.FIXED_SCALE),
            y=int(y * cls.FIXED_SCALE)
        )
    
    def to_float(self) -> Tuple[float, float]:
        """转换为浮点坐标"""
        return (self.x / self.FIXED_SCALE, self.y / self.FIXED_SCALE)
    
    def to_int(self) -> Tuple[int, int]:
        """转换为整数像素坐标"""
        return (self.x >> self.FIXED_SHIFT, self.y >> self.FIXED_SHIFT)
    
    def update_position(self, dt_ms: int):
        """
        更新位置
        
        Args:
            dt_ms: 时间增量（毫秒）
        """
        # v * dt / 1000
        self.x += (self.vx * dt_ms) // 1000
        self.y += (self.vy * dt_ms) // 1000
    
    def set_velocity(self, vx: float, vy: float):
        """设置速度（浮点输入）"""
        self.vx = int(vx * self.FIXED_SCALE)
        self.vy = int(vy * self.FIXED_SCALE)
    
    def get_bounds(self) -> Tuple[int, int, int, int]:
        """获取碰撞边界 (x1, y1, x2, y2)"""
        return (
            self.x,
            self.y,
            self.x + self.width,
            self.y + self.height
        )
    
    def serialize(self) -> dict:
        """序列化为字典"""
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
        """从字典反序列化"""
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
    所有计算使用整数，保证跨平台一致性
    """
    
    # 物理常量（定点数）
    GRAVITY = 980 << 16  # 980 像素/秒²
    FRICTION = 0.9  # 摩擦系数
    MAX_VELOCITY = 1000 << 16  # 最大速度
    
    # 游戏边界
    WORLD_WIDTH = 1920 << 16
    WORLD_HEIGHT = 1080 << 16
    
    def __init__(self):
        """初始化物理引擎"""
        self.entities: Dict[int, Entity] = {}
        self.collision_pairs: List[Tuple[int, int]] = []
    
    def add_entity(self, entity: Entity):
        """添加实体"""
        self.entities[entity.entity_id] = entity
    
    def remove_entity(self, entity_id: int):
        """移除实体"""
        if entity_id in self.entities:
            del self.entities[entity_id]
    
    def get_entity(self, entity_id: int) -> Optional[Entity]:
        """获取实体"""
        return self.entities.get(entity_id)
    
    def update(self, dt_ms: int):
        """
        更新物理模拟
        
        Args:
            dt_ms: 时间增量（毫秒）
        """
        # 1. 更新每个实体的位置
        for entity in self.entities.values():
            # 应用重力
            entity.vy += (self.GRAVITY * dt_ms) // 1000
            
            # 限制最大速度
            entity.vx = max(-self.MAX_VELOCITY, min(self.MAX_VELOCITY, entity.vx))
            entity.vy = max(-self.MAX_VELOCITY, min(self.MAX_VELOCITY, entity.vy))
            
            # 更新位置
            entity.update_position(dt_ms)
            
            # 应用摩擦力
            entity.vx = int(entity.vx * self.FRICTION)
        
        # 2. 边界碰撞
        self._handle_boundary_collision()
        
        # 3. 实体间碰撞
        self._handle_entity_collision()
    
    def _handle_boundary_collision(self):
        """处理边界碰撞"""
        for entity in self.entities.values():
            # 左边界
            if entity.x < 0:
                entity.x = 0
                entity.vx = 0
            
            # 右边界
            if entity.x + entity.width > self.WORLD_WIDTH:
                entity.x = self.WORLD_WIDTH - entity.width
                entity.vx = 0
            
            # 上边界
            if entity.y < 0:
                entity.y = 0
                entity.vy = 0
            
            # 下边界（地面）
            if entity.y + entity.height > self.WORLD_HEIGHT:
                entity.y = self.WORLD_HEIGHT - entity.height
                entity.vy = 0
    
    def _handle_entity_collision(self):
        """处理实体间碰撞（AABB）"""
        self.collision_pairs.clear()
        
        entities = sorted(self.entities.values(), key=lambda e: e.entity_id)
        n = len(entities)
        
        for i in range(n):
            for j in range(i + 1, n):
                if self._check_aabb_collision(entities[i], entities[j]):
                    self.collision_pairs.append((entities[i].entity_id, entities[j].entity_id))
                    self._resolve_collision(entities[i], entities[j])
    
    def _check_aabb_collision(self, a: Entity, b: Entity) -> bool:
        """AABB 碰撞检测"""
        return (a.x < b.x + b.width and
                a.x + a.width > b.x and
                a.y < b.y + b.height and
                a.y + a.height > b.y)
    
    def _resolve_collision(self, a: Entity, b: Entity):
        """解决碰撞（简单的分离）"""
        # 计算重叠
        overlap_x = min(a.x + a.width - b.x, b.x + b.width - a.x)
        overlap_y = min(a.y + a.height - b.y, b.y + b.height - a.y)
        
        # 沿最小重叠轴分离
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
        
        Args:
            entity_id: 实体ID
            input_flags: 输入标志
            speed: 移动速度（定点数）
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return
        
        # 解析输入方向
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
        """序列化当前状态"""
        return {
            'entities': {
                eid: entity.serialize() 
                for eid, entity in self.entities.items()
            },
            'collisions': self.collision_pairs.copy()
        }
    
    def deserialize_state(self, state: dict):
        """反序列化状态"""
        self.entities.clear()
        for eid, data in state.get('entities', {}).items():
            self.entities[int(eid)] = Entity.deserialize(data)


def distance_squared(a: Entity, b: Entity) -> int:
    """计算两实体间距离的平方（定点数）"""
    dx = a.x - b.x
    dy = a.y - b.y
    return (dx * dx + dy * dy) >> Entity.FIXED_SHIFT


def distance(a: Entity, b: Entity) -> int:
    """计算两实体间距离（定点数，整数平方根）"""
    dist_sq = distance_squared(a, b)
    return isqrt(dist_sq)


def isqrt(n: int) -> int:
    """整数平方根"""
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
