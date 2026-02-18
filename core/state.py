"""
Game state management and serialization
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import copy
import json
import hashlib


@dataclass
class StateSnapshot:
    """
    游戏状态快照
    用于回滚和校验
    """
    frame_id: int
    entities: Dict[int, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    hash: str = ""
    
    def compute_hash(self) -> str:
        """计算状态哈希"""
        state_str = json.dumps(
            {
                'frame': self.frame_id,
                'entities': {k: v for k, v in sorted(self.entities.items())}
            },
            sort_keys=True,
            separators=(',', ':')
        )
        return hashlib.md5(state_str.encode()).hexdigest()


class GameState:
    """
    游戏状态管理器
    负责状态的更新、快照和恢复
    """
    
    MAX_SNAPSHOTS = 60  # 保留最近60帧快照（2秒）
    
    def __init__(self):
        """初始化游戏状态"""
        self.frame_id = 0
        self.entities: Dict[int, Any] = {}
        self.player_entities: Dict[int, int] = {}  # player_id -> entity_id
        
        # 快照管理
        self.snapshots: Dict[int, StateSnapshot] = {}
        
        # 状态标志
        self.is_running = False
        self.is_paused = False
    
    def add_entity(self, entity) -> int:
        """
        添加实体
        
        Args:
            entity: 实体对象
        
        Returns:
            实体ID
        """
        self.entities[entity.entity_id] = entity
        return entity.entity_id
    
    def remove_entity(self, entity_id: int):
        """移除实体"""
        if entity_id in self.entities:
            del self.entities[entity_id]
    
    def get_entity(self, entity_id: int):
        """获取实体"""
        return self.entities.get(entity_id)
    
    def bind_player_entity(self, player_id: int, entity_id: int):
        """绑定玩家到实体"""
        self.player_entities[player_id] = entity_id
    
    def get_player_entity(self, player_id: int):
        """获取玩家对应的实体"""
        entity_id = self.player_entities.get(player_id)
        if entity_id:
            return self.entities.get(entity_id)
        return None
    
    def save_snapshot(self) -> StateSnapshot:
        """
        保存当前状态快照
        
        Returns:
            状态快照
        """
        snapshot = StateSnapshot(
            frame_id=self.frame_id,
            entities={
                eid: self._serialize_entity(entity)
                for eid, entity in self.entities.items()
            }
        )
        snapshot.hash = snapshot.compute_hash()
        
        self.snapshots[self.frame_id] = snapshot
        
        # 清理旧快照
        oldest = self.frame_id - self.MAX_SNAPSHOTS
        for fid in list(self.snapshots.keys()):
            if fid < oldest:
                del self.snapshots[fid]
        
        return snapshot
    
    def restore_snapshot(self, frame_id: int) -> bool:
        """
        恢复到指定帧的快照
        
        Args:
            frame_id: 目标帧ID
        
        Returns:
            是否恢复成功
        """
        if frame_id not in self.snapshots:
            return False
        
        snapshot = self.snapshots[frame_id]
        
        self.frame_id = snapshot.frame_id
        self.entities = {
            int(eid): self._deserialize_entity(data)
            for eid, data in snapshot.entities.items()
        }
        
        return True
    
    def rollback_to(self, frame_id: int) -> bool:
        """
        回滚到指定帧
        
        Args:
            frame_id: 目标帧ID
        
        Returns:
            是否回滚成功
        """
        return self.restore_snapshot(frame_id)
    
    def advance_frame(self):
        """推进帧"""
        self.frame_id += 1
    
    def get_current_frame(self) -> int:
        """获取当前帧ID"""
        return self.frame_id
    
    def serialize(self) -> dict:
        """序列化完整状态"""
        return {
            'frame_id': self.frame_id,
            'entities': {
                str(eid): self._serialize_entity(entity)
                for eid, entity in self.entities.items()
            },
            'player_entities': {
                str(pid): eid 
                for pid, eid in self.player_entities.items()
            },
            'is_running': self.is_running,
            'is_paused': self.is_paused
        }
    
    def deserialize(self, data: dict):
        """反序列化状态"""
        self.frame_id = data.get('frame_id', 0)
        self.is_running = data.get('is_running', False)
        self.is_paused = data.get('is_paused', False)
        
        # 注意：实际的实体反序列化需要知道实体类型
        # 这里只是基础实现
    
    def compute_state_hash(self) -> str:
        """计算当前状态哈希"""
        snapshot = StateSnapshot(
            frame_id=self.frame_id,
            entities={
                eid: self._serialize_entity(entity)
                for eid, entity in self.entities.items()
            }
        )
        return snapshot.compute_hash()
    
    def _serialize_entity(self, entity) -> dict:
        """序列化实体"""
        if hasattr(entity, 'serialize'):
            return entity.serialize()
        return {'id': getattr(entity, 'entity_id', 0)}
    
    def _deserialize_entity(self, data: dict):
        """反序列化实体（需要子类实现具体类型）"""
        # 基础实现，返回数据字典
        return data
    
    def copy(self) -> 'GameState':
        """创建状态副本"""
        new_state = GameState()
        new_state.frame_id = self.frame_id
        new_state.is_running = self.is_running
        new_state.is_paused = self.is_paused
        new_state.player_entities = self.player_entities.copy()
        
        # 深拷贝实体（简化版）
        new_state.entities = copy.deepcopy(self.entities)
        
        return new_state


class StateValidator:
    """
    状态校验器
    用于检测状态不一致
    """
    
    def __init__(self):
        """初始化校验器"""
        self.hash_history: Dict[int, str] = {}
        self.mismatches: List[dict] = []
    
    def record_hash(self, frame_id: int, hash_value: str):
        """记录帧哈希"""
        self.hash_history[frame_id] = hash_value
    
    def verify_hash(self, frame_id: int, expected_hash: str) -> bool:
        """
        验证哈希
        
        Args:
            frame_id: 帧ID
            expected_hash: 期望的哈希值
        
        Returns:
            True 如果匹配
        """
        if frame_id not in self.hash_history:
            return True  # 没有记录，跳过
        
        actual = self.hash_history[frame_id]
        
        if actual != expected_hash:
            self.mismatches.append({
                'frame_id': frame_id,
                'expected': expected_hash,
                'actual': actual
            })
            return False
        
        return True
    
    def get_mismatches(self) -> List[dict]:
        """获取所有不匹配记录"""
        return self.mismatches.copy()
    
    def clear_mismatches(self):
        """清空不匹配记录"""
        self.mismatches.clear()
