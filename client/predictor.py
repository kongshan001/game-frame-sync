"""
Client-side prediction and rollback system
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import copy

from core.frame import Frame
from core.state import GameState
from core.input import PlayerInput
from core.physics import PhysicsEngine, Entity
from core.fixed import FixedPoint
from core.config import CONFIG


@dataclass
class PredictionResult:
    """预测结果"""
    frame_id: int
    predicted: bool      # 是否是预测帧
    correct: bool        # 预测是否正确
    rollback_needed: bool  # 是否需要回滚


class ClientPredictor:
    """
    客户端预测和回滚系统
    
    核心功能：
    1. 本地立即执行玩家输入（预测）
    2. 保存状态快照用于回滚
    3. 收到服务器帧时校验预测
    4. 预测错误时回滚并重放
    """
    
    MAX_PREDICTED_FRAMES = 30  # 最大预测帧数（1秒）
    MAX_SNAPSHOTS = 60        # 最大快照数
    
    def __init__(self, game_state: GameState, physics: PhysicsEngine, player_id: int):
        """
        初始化预测器
        
        Args:
            game_state: 游戏状态
            physics: 物理引擎
            player_id: 本地玩家ID
        """
        self.game_state = game_state
        self.physics = physics
        self.player_id = player_id
        
        # 预测相关
        self.predicted_frames: Dict[int, Frame] = {}
        self.unconfirmed_inputs: List[Tuple[int, bytes]] = []  # [(frame_id, input)]
        
        # 状态快照
        self.state_snapshots: Dict[int, dict] = {}
        
        # 统计
        self.prediction_count = 0
        self.correct_count = 0
        self.rollback_count = 0
        self.last_prediction_result: Optional[PredictionResult] = None
    
    def predict_frame(self, frame_id: int, my_input: bytes, 
                      other_players: List[int]) -> Frame:
        """
        预测执行一帧
        
        Args:
            frame_id: 帧ID
            my_input: 本地玩家输入
            other_players: 其他玩家ID列表
        
        Returns:
            预测的帧
        """
        # 保存当前状态快照
        self._save_snapshot(frame_id)
        
        # 创建预测帧
        predicted_inputs = {self.player_id: my_input}
        
        # 预测其他玩家输入（使用上一帧的输入）
        for other_id in other_players:
            last_input = self._get_last_input(other_id)
            predicted_inputs[other_id] = last_input
        
        predicted_frame = Frame(
            frame_id=frame_id,
            inputs=predicted_inputs,
            confirmed=False
        )
        
        # 保存预测帧
        self.predicted_frames[frame_id] = predicted_frame
        
        # 保存未确认的输入
        self.unconfirmed_inputs.append((frame_id, my_input))
        
        # 立即执行预测
        self._apply_frame(predicted_frame)
        
        self.prediction_count += 1
        
        return predicted_frame
    
    def on_server_frame(self, server_frame: Frame, other_players: List[int]) -> PredictionResult:
        """
        收到服务器帧，校验预测
        
        Args:
            server_frame: 服务器帧
            other_players: 其他玩家ID列表
        
        Returns:
            预测结果
        """
        frame_id = server_frame.frame_id
        
        # 如果这不是预测帧，直接应用
        if frame_id not in self.predicted_frames:
            self._apply_frame(server_frame)
            self.last_prediction_result = PredictionResult(
                frame_id=frame_id,
                predicted=False,
                correct=True,
                rollback_needed=False
            )
            return self.last_prediction_result
        
        predicted = self.predicted_frames[frame_id]
        
        # 比较预测与实际
        is_correct = self._compare_inputs(predicted.inputs, server_frame.inputs)
        
        if is_correct:
            # 预测正确
            self.correct_count += 1
            del self.predicted_frames[frame_id]
            self._cleanup_confirmed_input(frame_id)
            
            self.last_prediction_result = PredictionResult(
                frame_id=frame_id,
                predicted=True,
                correct=True,
                rollback_needed=False
            )
        else:
            # 预测错误，需要回滚
            self._rollback_and_replay(frame_id, server_frame, other_players)
            self.rollback_count += 1
            
            self.last_prediction_result = PredictionResult(
                frame_id=frame_id,
                predicted=True,
                correct=False,
                rollback_needed=True
            )
        
        return self.last_prediction_result
    
    def _save_snapshot(self, frame_id: int):
        """保存状态快照"""
        snapshot = {
            'frame_id': self.game_state.frame_id,
            'entities': {},
            'physics_state': self.physics.serialize_state()
        }
        
        # 保存所有实体
        for eid, entity in self.game_state.entities.items():
            snapshot['entities'][eid] = entity.serialize()
        
        self.state_snapshots[frame_id] = snapshot
        
        # 清理旧快照
        oldest = frame_id - self.MAX_SNAPSHOTS
        for fid in list(self.state_snapshots.keys()):
            if fid < oldest:
                del self.state_snapshots[fid]
    
    def _restore_snapshot(self, frame_id: int) -> bool:
        """恢复状态快照"""
        if frame_id not in self.state_snapshots:
            return False
        
        snapshot = self.state_snapshots[frame_id]
        
        # 恢复游戏状态
        self.game_state.frame_id = snapshot['frame_id']
        self.game_state.entities.clear()
        
        # 恢复实体
        for eid, data in snapshot['entities'].items():
            entity = Entity.deserialize(data)
            self.game_state.entities[int(eid)] = entity
        
        # 恢复物理状态
        self.physics.deserialize_state(snapshot['physics_state'])
        
        return True
    
    def _get_last_input(self, player_id: int) -> bytes:
        """获取玩家上一帧的输入"""
        # 从最近确认的帧中获取
        for frame_id in sorted(self.predicted_frames.keys(), reverse=True):
            frame = self.predicted_frames[frame_id]
            if player_id in frame.inputs:
                return frame.inputs[player_id]
        
        # 默认空输入
        return b''
    
    def _compare_inputs(self, predicted: Dict[int, bytes], actual: Dict[int, bytes]) -> bool:
        """比较预测输入和实际输入"""
        for player_id in actual:
            if player_id == self.player_id:
                continue  # 跳过自己的输入
            
            pred_input = predicted.get(player_id, b'')
            actual_input = actual.get(player_id, b'')
            
            if pred_input != actual_input:
                return False
        
        return True
    
    def _apply_frame(self, frame: Frame):
        """应用帧输入"""
        from core.input import PlayerInput, InputFlags
        
        for player_id, input_data in frame.inputs.items():
            if not input_data:
                continue
            
            try:
                parsed = PlayerInput.deserialize(input_data)
                entity = self.game_state.get_player_entity(player_id)
                if entity:
                    self.physics.apply_input(
                        entity.entity_id, 
                        parsed.flags,
                        int(CONFIG.game.PLAYER_SPEED * FixedPoint.SCALE)
                    )
            except Exception:
                pass
        
        # 更新物理
        self.physics.update(33)
        
        # 推进帧
        self.game_state.frame_id = frame.frame_id
    
    def _rollback_and_replay(self, wrong_frame_id: int, correct_frame: Frame, 
                             other_players: List[int]):
        """回滚并重放"""
        # 1. 回滚到错误帧之前
        self._restore_snapshot(wrong_frame_id)
        
        # 2. 应用正确的帧
        self._apply_frame(correct_frame)
        
        # 3. 重放后续预测帧
        frames_to_replay = sorted([
            fid for fid in self.predicted_frames.keys() 
            if fid > wrong_frame_id
        ])
        
        for frame_id in frames_to_replay:
            # 更新预测帧中的其他玩家输入为实际值
            predicted = self.predicted_frames[frame_id]
            
            # 重新应用帧（使用可能的更新输入）
            self._apply_frame(predicted)
        
        # 4. 清理已处理的预测帧
        for fid in list(self.predicted_frames.keys()):
            if fid <= wrong_frame_id:
                del self.predicted_frames[fid]
    
    def _cleanup_confirmed_input(self, confirmed_frame_id: int):
        """清理已确认的输入"""
        self.unconfirmed_inputs = [
            (fid, inp) for fid, inp in self.unconfirmed_inputs
            if fid > confirmed_frame_id
        ]
    
    def get_prediction_accuracy(self) -> float:
        """获取预测准确率"""
        if self.prediction_count == 0:
            return 0.0
        return self.correct_count / self.prediction_count * 100
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'prediction_count': self.prediction_count,
            'correct_count': self.correct_count,
            'rollback_count': self.rollback_count,
            'accuracy': self.get_prediction_accuracy(),
            'unconfirmed_inputs': len(self.unconfirmed_inputs),
            'predicted_frames': len(self.predicted_frames),
            'snapshots': len(self.state_snapshots)
        }


class InterpolationRenderer:
    """
    插值渲染器
    
    在逻辑帧之间进行平滑插值，让画面更流畅
    """
    
    def __init__(self, game_state: GameState):
        self.game_state = game_state
        self.prev_state: Optional[dict] = None
        self.curr_state: Optional[dict] = None
        self.render_alpha = 0.0
    
    def on_logic_frame(self):
        """逻辑帧更新时调用"""
        self.prev_state = self.curr_state
        self.curr_state = self._capture_state()
        self.render_alpha = 0.0
    
    def update(self, dt: float, frame_time: float):
        """更新插值因子"""
        if frame_time > 0:
            self.render_alpha = min(1.0, dt / frame_time)
    
    def get_interpolated_position(self, entity_id: int) -> Optional[Tuple[float, float]]:
        """获取插值后的位置"""
        if self.prev_state is None or self.curr_state is None:
            entity = self.game_state.get_entity(entity_id)
            if entity:
                return entity.to_float()
            return None
        
        prev_entity = self.prev_state.get('entities', {}).get(entity_id)
        curr_entity = self.curr_state.get('entities', {}).get(entity_id)
        
        if prev_entity is None or curr_entity is None:
            entity = self.game_state.get_entity(entity_id)
            if entity:
                return entity.to_float()
            return None
        
        # 线性插值
        prev_x = prev_entity['x'] / Entity.FIXED_SCALE
        prev_y = prev_entity['y'] / Entity.FIXED_SCALE
        curr_x = curr_entity['x'] / Entity.FIXED_SCALE
        curr_y = curr_entity['y'] / Entity.FIXED_SCALE
        
        x = prev_x + (curr_x - prev_x) * self.render_alpha
        y = prev_y + (curr_y - prev_y) * self.render_alpha
        
        return (x, y)
    
    def _capture_state(self) -> dict:
        """捕获当前状态"""
        entities = {}
        for eid, entity in self.game_state.entities.items():
            entities[eid] = entity.serialize()
        
        return {
            'frame_id': self.game_state.frame_id,
            'entities': entities
        }
