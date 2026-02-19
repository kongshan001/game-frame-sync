"""
游戏状态管理和序列化

本模块提供游戏状态的管理功能：
- StateSnapshot: 状态快照，用于保存和恢复状态
- GameState: 游戏状态管理器，负责状态更新、快照和恢复
- StateValidator: 状态校验器，用于检测状态不一致
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
    
    保存某一时刻的完整游戏状态，用于：
    1. 客户端预测回滚
    2. 状态校验（检测作弊/同步问题）
    3. 断线重连
    
    属性:
        frame_id (int): 
            快照对应的帧ID。
            用于确定快照的时间点。
        
        entities (Dict[int, dict]): 
            所有实体的序列化数据。
            键为 entity_id，值为实体属性字典。
            例如：{0: {'x': 100, 'y': 200, 'hp': 100}, ...}
        
        metadata (dict): 
            额外的元数据。
            可包含游戏模式、地图信息等。
        
        hash (str): 
            状态的 MD5 哈希值。
            用于快速比较两个状态是否相同。
            例如："a1b2c3d4e5f6..."
    """
    frame_id: int
    entities: Dict[int, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    hash: str = ""
    
    def compute_hash(self) -> str:
        """
        计算状态的确定性哈希
        
        使用 MD5 算法对序列化后的状态计算哈希。
        相同的状态永远产生相同的哈希。
        
        Returns:
            32字符的十六进制哈希字符串
        """
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
    
    负责管理整个游戏的状态，包括：
    - 所有游戏实体
    - 玩家与实体的映射
    - 状态快照和恢复
    - 状态哈希计算
    
    属性:
        frame_id (int): 
            当前游戏帧ID。
            每帧更新后递增。
            用于同步和状态追踪。
        
        entities (Dict[int, Any]): 
            所有游戏实体的字典。
            键为 entity_id，值为 Entity 对象。
            例如：{0: Entity(id=0, x=100, ...), 1: Entity(...)}
        
        player_entities (Dict[int, int]): 
            玩家ID到实体ID的映射。
            键为 player_id，值为 entity_id。
            用于快速查找玩家对应的实体。
            例如：{0: 0, 1: 1} 表示玩家0控制实体0
        
        snapshots (Dict[int, StateSnapshot]): 
            保存的状态快照。
            键为 frame_id，值为 StateSnapshot。
            用于回滚和状态校验。
        
        is_running (bool): 
            游戏是否正在运行。
            True = 游戏进行中，False = 游戏停止。
        
        is_paused (bool): 
            游戏是否暂停。
            暂停时不更新状态。
    
    类常量:
        MAX_SNAPSHOTS (60): 最大快照数量（2秒@30fps）
    """
    
    MAX_SNAPSHOTS = 60
    
    def __init__(self):
        """初始化游戏状态"""
        self.frame_id = 0
        self.entities: Dict[int, Any] = {}
        self.player_entities: Dict[int, int] = {}
        self.snapshots: Dict[int, StateSnapshot] = {}
        self.is_running = False
        self.is_paused = False
    
    def add_entity(self, entity) -> int:
        """
        添加实体到游戏状态
        
        Args:
            entity: 实体对象（需要有 entity_id 属性）
        
        Returns:
            实体的 ID
        """
        self.entities[entity.entity_id] = entity
        return entity.entity_id
    
    def remove_entity(self, entity_id: int):
        """
        从游戏状态中移除实体
        
        Args:
            entity_id: 要移除的实体ID
        """
        if entity_id in self.entities:
            del self.entities[entity_id]
    
    def get_entity(self, entity_id: int):
        """
        获取实体
        
        Args:
            entity_id: 实体ID
        
        Returns:
            Entity 对象，不存在则返回 None
        """
        return self.entities.get(entity_id)
    
    def bind_player_entity(self, player_id: int, entity_id: int):
        """
        绑定玩家到实体
        
        建立玩家ID和实体ID的映射关系，
        用于快速查找玩家控制的角色。
        
        Args:
            player_id: 玩家ID
            entity_id: 实体ID
        """
        self.player_entities[player_id] = entity_id
    
    def get_player_entity(self, player_id: int):
        """
        获取玩家对应的实体
        
        Args:
            player_id: 玩家ID
        
        Returns:
            玩家控制的 Entity，不存在则返回 None
        """
        entity_id = self.player_entities.get(player_id)
        if entity_id:
            return self.entities.get(entity_id)
        return None
    
    def save_snapshot(self) -> StateSnapshot:
        """
        保存当前状态的快照
        
        创建并保存当前帧的完整状态快照，
        用于后续的回滚或校验。
        
        Returns:
            创建的 StateSnapshot
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
        
        将游戏状态回退到之前保存的快照。
        用于客户端预测回滚。
        
        Args:
            frame_id: 要恢复的帧ID
        
        Returns:
            True 如果恢复成功，False 如果快照不存在
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
        回滚到指定帧（restore_snapshot 的别名）
        
        Args:
            frame_id: 目标帧ID
        
        Returns:
            是否回滚成功
        """
        return self.restore_snapshot(frame_id)
    
    def advance_frame(self):
        """推进帧计数器"""
        self.frame_id += 1
    
    def get_current_frame(self) -> int:
        """
        获取当前帧ID
        
        Returns:
            当前帧ID
        """
        return self.frame_id
    
    def serialize(self) -> dict:
        """
        序列化完整状态
        
        将整个游戏状态转换为可传输/存储的字典格式。
        
        Returns:
            包含完整状态的字典
        """
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
        """
        从字典反序列化状态
        
        Args:
            data: 序列化的状态数据
        """
        self.frame_id = data.get('frame_id', 0)
        self.is_running = data.get('is_running', False)
        self.is_paused = data.get('is_paused', False)
    
    def compute_state_hash(self) -> str:
        """
        计算当前状态的哈希值
        
        用于快速比较两个状态是否相同。
        
        Returns:
            MD5 哈希字符串
        """
        snapshot = StateSnapshot(
            frame_id=self.frame_id,
            entities={
                eid: self._serialize_entity(entity)
                for eid, entity in self.entities.items()
            }
        )
        return snapshot.compute_hash()
    
    def _serialize_entity(self, entity) -> dict:
        """序列化单个实体"""
        if hasattr(entity, 'serialize'):
            return entity.serialize()
        return {'id': getattr(entity, 'entity_id', 0)}
    
    def _deserialize_entity(self, data: dict):
        """反序列化实体（需要子类实现）"""
        return data
    
    def copy(self) -> 'GameState':
        """
        创建状态的深拷贝
        
        Returns:
            新的 GameState 实例
        """
        new_state = GameState()
        new_state.frame_id = self.frame_id
        new_state.is_running = self.is_running
        new_state.is_paused = self.is_paused
        new_state.player_entities = self.player_entities.copy()
        new_state.entities = copy.deepcopy(self.entities)
        return new_state


class StateValidator:
    """
    状态校验器
    
    用于检测不同客户端之间的状态不一致。
    通过比较状态哈希来发现同步问题。
    
    使用场景:
    1. 服务器验证客户端状态
    2. 客户端自检（与服务器哈希对比）
    3. 调试帧同步问题
    
    属性:
        hash_history (Dict[int, str]): 
            记录每帧的状态哈希。
            键为 frame_id，值为哈希字符串。
            用于后续校验。
            例如：{100: "a1b2c3...", 101: "d4e5f6..."}
        
        mismatches (List[dict]): 
            记录所有哈希不匹配的情况。
            每个元素包含 frame_id、期望值、实际值。
            用于调试和分析同步问题。
            例如：[{'frame_id': 100, 'expected': 'a1b2...', 'actual': 'x9y8...'}]
    """
    
    def __init__(self):
        """初始化校验器"""
        self.hash_history: Dict[int, str] = {}
        self.mismatches: List[dict] = []
    
    def record_hash(self, frame_id: int, hash_value: str):
        """
        记录帧的哈希值
        
        Args:
            frame_id: 帧ID
            hash_value: 状态哈希
        """
        self.hash_history[frame_id] = hash_value
    
    def verify_hash(self, frame_id: int, expected_hash: str) -> bool:
        """
        验证帧的哈希是否匹配
        
        Args:
            frame_id: 帧ID
            expected_hash: 期望的哈希值
        
        Returns:
            True 如果匹配或没有记录，False 如果不匹配
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
        """
        获取所有不匹配记录
        
        Returns:
            不匹配记录的列表
        """
        return self.mismatches.copy()
    
    def clear_mismatches(self):
        """清空不匹配记录"""
        self.mismatches.clear()
