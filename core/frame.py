"""
Frame data structures and management
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import deque
import time


@dataclass
class Frame:
    """游戏帧数据"""
    frame_id: int
    inputs: Dict[int, bytes] = field(default_factory=dict)  # {player_id: input_data}
    confirmed: bool = False
    timestamp: float = field(default_factory=time.time)
    
    def get_input(self, player_id: int) -> Optional[bytes]:
        """获取玩家输入"""
        return self.inputs.get(player_id)
    
    def set_input(self, player_id: int, input_data: bytes):
        """设置玩家输入"""
        self.inputs[player_id] = input_data
    
    def is_complete(self, player_count: int) -> bool:
        """检查帧是否完整"""
        return len(self.inputs) == player_count


class FrameBuffer:
    """
    帧缓冲管理器
    用于平滑网络延迟，存储待执行的帧
    """
    
    def __init__(self, buffer_size: int = 3):
        """
        初始化帧缓冲
        
        Args:
            buffer_size: 缓冲帧数，用于抵消网络延迟
        """
        self.buffer_size = buffer_size
        self.frames: Dict[int, Frame] = {}
        self.pending_inputs: Dict[int, Dict[int, bytes]] = {}
        self.ready_queue: deque = deque(maxlen=1000)
    
    def add_input(self, frame_id: int, player_id: int, input_data: bytes):
        """
        添加玩家输入
        
        Args:
            frame_id: 帧ID
            player_id: 玩家ID
            input_data: 输入数据（二进制）
        """
        # 验证输入
        if frame_id < 0:
            return
        if not isinstance(input_data, bytes):
            return
        if len(input_data) > 1024:  # 限制输入大小
            return
            
        if frame_id not in self.pending_inputs:
            self.pending_inputs[frame_id] = {}
        self.pending_inputs[frame_id][player_id] = input_data
    
    def try_commit_frame(self, frame_id: int, player_count: int) -> Optional[Frame]:
        """
        尝试提交帧（所有玩家输入到齐）
        
        Args:
            frame_id: 帧ID
            player_count: 玩家总数
        
        Returns:
            如果帧完整则返回Frame，否则返回None
        """
        if frame_id not in self.pending_inputs:
            return None
        
        pending = self.pending_inputs[frame_id]
        if len(pending) == player_count:
            frame = Frame(
                frame_id=frame_id,
                inputs=dict(pending),
                confirmed=True
            )
            self.frames[frame_id] = frame
            self.ready_queue.append(frame_id)
            del self.pending_inputs[frame_id]
            return frame
        
        return None
    
    def get_frame(self, frame_id: int) -> Optional[Frame]:
        """获取帧数据"""
        return self.frames.get(frame_id)
    
    def get_next_ready_frame(self) -> Optional[Frame]:
        """获取下一个可执行的帧"""
        if self.ready_queue:
            frame_id = self.ready_queue.popleft()
            return self.frames.get(frame_id)
        return None
    
    def get_executable_frame_id(self, current_frame: int) -> int:
        """
        获取当前可执行的帧ID
        考虑帧缓冲，延迟执行以等待网络数据
        
        Args:
            current_frame: 当前服务器帧ID
        
        Returns:
            可执行的帧ID
        """
        return current_frame - self.buffer_size
    
    def cleanup_old_frames(self, oldest_frame: int):
        """
        清理旧帧数据
        
        Args:
            oldest_frame: 最小保留帧ID
        """
        for frame_id in list(self.frames.keys()):
            if frame_id < oldest_frame:
                del self.frames[frame_id]
        
        for frame_id in list(self.pending_inputs.keys()):
            if frame_id < oldest_frame:
                del self.pending_inputs[frame_id]
    
    def get_buffer_status(self) -> dict:
        """获取缓冲状态"""
        return {
            'buffer_size': self.buffer_size,
            'ready_frames': len(self.ready_queue),
            'pending_frames': len(self.pending_inputs),
            'total_stored': len(self.frames)
        }


class FrameEngine:
    """
    帧同步引擎
    负责收集输入、生成帧、管理帧缓冲
    """
    
    def __init__(self, player_count: int = 2, buffer_size: int = 3):
        """
        初始化帧引擎
        
        Args:
            player_count: 玩家数量
            buffer_size: 帧缓冲大小
        """
        self.player_count = player_count
        self.buffer_size = buffer_size
        self.frame_buffer = FrameBuffer(buffer_size)
        self.current_frame = 0
        self.frame_history: Dict[int, Frame] = {}  # 修复：使用字典而非列表
        self.max_history = 300  # 保留最近10秒（30fps）
    
    def add_input(self, frame_id: int, player_id: int, input_data: bytes):
        """
        添加玩家输入
        
        Args:
            frame_id: 目标帧ID
            player_id: 玩家ID
            input_data: 输入数据
        """
        self.frame_buffer.add_input(frame_id, player_id, input_data)
    
    def tick(self) -> Optional[Frame]:
        """
        帧引擎时钟周期
        检查是否有完整帧可以执行
        
        Returns:
            如果有完整帧则返回，否则返回None
        """
        # 尝试提交当前帧
        frame = self.frame_buffer.try_commit_frame(
            self.current_frame, 
            self.player_count
        )
        
        if frame:
            self.frame_history[frame.frame_id] = frame  # 修复：使用 frame_id 作为 key
            
            # 清理旧历史
            oldest = self.current_frame - self.max_history
            for fid in list(self.frame_history.keys()):
                if fid < oldest:
                    del self.frame_history[fid]
            
            self.current_frame += 1
            return frame
        
        return None
    
    def force_tick(self) -> Frame:
        """
        强制推进帧
        用于超时情况，使用空输入填充
        
        Returns:
            强制生成的帧
        """
        # 获取已收集的输入
        pending = self.frame_buffer.pending_inputs.get(self.current_frame, {})
        
        # 填充缺失的玩家输入（使用空输入）
        for player_id in range(self.player_count):
            if player_id not in pending:
                pending[player_id] = b''  # 空输入
        
        frame = Frame(
            frame_id=self.current_frame,
            inputs=dict(pending),
            confirmed=False  # 强制帧未完全确认
        )
        
        self.frame_history[frame.frame_id] = frame  # 修复：使用 frame_id 作为 key
        
        # 清理旧历史
        oldest = self.current_frame - self.max_history
        for fid in list(self.frame_history.keys()):
            if fid < oldest:
                del self.frame_history[fid]
        
        # 清理pending
        if self.current_frame in self.frame_buffer.pending_inputs:
            del self.frame_buffer.pending_inputs[self.current_frame]
        
        self.current_frame += 1
        return frame
    
    def get_frame(self, frame_id: int) -> Optional[Frame]:
        """获取历史帧"""
        return self.frame_history.get(frame_id)  # 修复：直接使用字典查找
    
    def get_current_frame_id(self) -> int:
        """获取当前帧ID"""
        return self.current_frame
    
    def get_stats(self) -> dict:
        """获取引擎统计信息"""
        return {
            'current_frame': self.current_frame,
            'player_count': self.player_count,
            'buffer_size': self.buffer_size,
            'history_size': len(self.frame_history),
            **self.frame_buffer.get_buffer_status()
        }
