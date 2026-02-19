"""
帧数据结构和管理

本模块提供帧同步的核心数据结构：
- Frame: 单帧数据，包含所有玩家的输入
- FrameBuffer: 帧缓冲区，用于平滑网络延迟
- FrameEngine: 帧同步引擎，负责收集输入、生成帧、管理历史
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import deque
import time


@dataclass
class Frame:
    """
    游戏帧数据
    
    表示帧同步中的一个逻辑帧，包含该帧所有玩家的输入数据。
    帧是帧同步的基本单位，所有客户端在收到相同的帧数据后执行相同的逻辑。
    
    属性:
        frame_id (int): 
            帧的唯一标识符，从0开始递增。
            用于确定帧的执行顺序和历史查询。
            例如：第100帧的 frame_id = 100
        
        inputs (Dict[int, bytes]): 
            该帧所有玩家的输入数据。
            键为 player_id (0, 1, 2, ...)，值为序列化后的输入字节。
            例如：{0: b'\\x00\\x01...', 1: b'\\x00\\x02...'}
            当 inputs 的数量等于 player_count 时，该帧才算完整。
        
        confirmed (bool): 
            该帧是否已确认（所有玩家输入都已到齐）。
            True = 所有玩家都发送了这一帧的输入
            False = 部分玩家输入缺失（超时强制推进时使用）
        
        timestamp (float): 
            该帧创建的时间戳（Unix时间戳，秒）。
            用于超时检测和延迟统计。
            例如：1708345678.123456
    """
    frame_id: int
    inputs: Dict[int, bytes] = field(default_factory=dict)
    confirmed: bool = False
    timestamp: float = field(default_factory=time.time)
    
    def get_input(self, player_id: int) -> Optional[bytes]:
        """
        获取指定玩家的输入
        
        Args:
            player_id: 玩家ID（0, 1, 2, ...）
        
        Returns:
            玩家的输入数据（字节），如果不存在则返回 None
        """
        return self.inputs.get(player_id)
    
    def set_input(self, player_id: int, input_data: bytes):
        """
        设置玩家输入
        
        Args:
            player_id: 玩家ID
            input_data: 序列化后的输入数据（字节）
        """
        self.inputs[player_id] = input_data
    
    def is_complete(self, player_count: int) -> bool:
        """
        检查帧是否完整（所有玩家输入都已到齐）
        
        Args:
            player_count: 游戏中的玩家总数
        
        Returns:
            True 如果输入数量等于玩家数量
        """
        return len(self.inputs) == player_count


class FrameBuffer:
    """
    帧缓冲管理器
    
    用于平滑网络延迟，存储待执行的帧数据。
    
    工作原理：
    1. 服务器发送帧 N 时，客户端还在执行帧 N-buffer_size
    2. 这给网络延迟留出了缓冲时间
    3. buffer_size 越大，对网络抖动的容忍度越高，但延迟也越高
    
    典型配置：
    - buffer_size = 3: 约 100ms 延迟，适合局域网
    - buffer_size = 5: 约 166ms 延迟，适合互联网
    
    属性:
        buffer_size (int): 
            缓冲帧数，决定延迟补偿的大小。
            例如：buffer_size=3 表示客户端落后服务器3帧执行
            
        frames (Dict[int, Frame]): 
            已完成（所有玩家输入到齐）的帧数据。
            键为 frame_id，值为 Frame 对象。
            用于获取待执行的帧和历史查询。
            
        pending_inputs (Dict[int, Dict[int, bytes]]): 
            尚未完成的帧的输入数据。
            外层键为 frame_id，内层键为 player_id，值为输入字节。
            当某帧的玩家数达到 player_count 时，会被移动到 frames。
            
        ready_queue (deque): 
            已准备好可执行的帧ID队列。
            按 frame_id 排序，用于按顺序获取帧执行。
            maxlen=1000 防止内存无限增长。
    """
    
    def __init__(self, buffer_size: int = 3):
        """
        初始化帧缓冲
        
        Args:
            buffer_size: 缓冲帧数，用于抵消网络延迟。
                        值越大延迟越高，但对网络抖动越稳定。
        """
        self.buffer_size = buffer_size
        self.frames: Dict[int, Frame] = {}
        self.pending_inputs: Dict[int, Dict[int, bytes]] = {}
        self.ready_queue: deque = deque(maxlen=1000)
    
    def add_input(self, frame_id: int, player_id: int, input_data: bytes):
        """
        添加玩家输入到待处理队列
        
        Args:
            frame_id: 目标帧ID
            player_id: 玩家ID
            input_data: 输入数据（二进制）
        
        Note:
            - frame_id < 0 的输入会被忽略
            - 超过 1024 字节的输入会被拒绝
        """
        # 验证输入
        if frame_id < 0:
            return
        if not isinstance(input_data, bytes):
            return
        if len(input_data) > 1024:
            return
            
        if frame_id not in self.pending_inputs:
            self.pending_inputs[frame_id] = {}
        self.pending_inputs[frame_id][player_id] = input_data
    
    def try_commit_frame(self, frame_id: int, player_count: int) -> Optional[Frame]:
        """
        尝试提交帧（检查是否所有玩家输入都已到齐）
        
        Args:
            frame_id: 要检查的帧ID
            player_count: 玩家总数
        
        Returns:
            如果帧完整则返回 Frame 对象，否则返回 None
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
        """
        获取已提交的帧数据
        
        Args:
            frame_id: 帧ID
        
        Returns:
            Frame 对象，不存在则返回 None
        """
        return self.frames.get(frame_id)
    
    def get_next_ready_frame(self) -> Optional[Frame]:
        """
        获取下一个可执行的帧（按帧ID顺序）
        
        Returns:
            下一个待执行的 Frame，队列为空则返回 None
        """
        if self.ready_queue:
            frame_id = self.ready_queue.popleft()
            return self.frames.get(frame_id)
        return None
    
    def get_executable_frame_id(self, current_frame: int) -> int:
        """
        获取当前可执行的帧ID（考虑缓冲）
        
        Args:
            current_frame: 当前服务器帧ID
        
        Returns:
            可执行的帧ID = current_frame - buffer_size
        """
        return current_frame - self.buffer_size
    
    def cleanup_old_frames(self, oldest_frame: int):
        """
        清理旧的帧数据以释放内存
        
        Args:
            oldest_frame: 最小保留的帧ID，小于此值的帧会被删除
        """
        for frame_id in list(self.frames.keys()):
            if frame_id < oldest_frame:
                del self.frames[frame_id]
        
        for frame_id in list(self.pending_inputs.keys()):
            if frame_id < oldest_frame:
                del self.pending_inputs[frame_id]
    
    def get_buffer_status(self) -> dict:
        """
        获取缓冲区状态统计
        
        Returns:
            包含缓冲区状态的字典：
            - buffer_size: 配置的缓冲大小
            - ready_frames: 已准备好执行的帧数
            - pending_frames: 等待输入的帧数
            - total_stored: 总共存储的帧数
        """
        return {
            'buffer_size': self.buffer_size,
            'ready_frames': len(self.ready_queue),
            'pending_frames': len(self.pending_inputs),
            'total_stored': len(self.frames)
        }


class FrameEngine:
    """
    帧同步引擎
    
    负责协调帧同步的核心组件：
    1. 收集所有玩家的输入
    2. 等待帧完整后生成 Frame
    3. 管理帧历史记录
    4. 提供超时强制推进功能
    
    使用示例:
        engine = FrameEngine(player_count=2, buffer_size=3)
        
        # 每帧收集输入
        engine.add_input(frame_id, player_id, input_data)
        
        # 尝试推进
        frame = engine.tick()
        if frame:
            execute_frame(frame)  # 执行游戏逻辑
    
    属性:
        player_count (int): 
            游戏中的玩家数量。
            决定一帧需要多少个输入才算完整。
            
        buffer_size (int): 
            帧缓冲大小。
            传递给 FrameBuffer 使用。
            
        frame_buffer (FrameBuffer): 
            帧缓冲管理器实例。
            负责存储和管理帧数据。
            
        current_frame (int): 
            当前正在等待的帧ID。
            每次成功 tick() 后会 +1。
            例如：如果 current_frame=100，表示正在收集第100帧的输入。
            
        frame_history (Dict[int, Frame]): 
            已执行帧的历史记录。
            键为 frame_id，值为 Frame 对象。
            用于回滚、重放和调试。
            
        max_history (int): 
            保留的最大历史帧数。
            默认 300 帧（30fps 下约 10 秒）。
            超过此数量的旧帧会被自动清理。
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
        self.frame_history: Dict[int, Frame] = {}
        self.max_history = 300
    
    def add_input(self, frame_id: int, player_id: int, input_data: bytes):
        """
        添加玩家输入
        
        Args:
            frame_id: 目标帧ID
            player_id: 玩家ID
            input_data: 序列化后的输入数据
        """
        self.frame_buffer.add_input(frame_id, player_id, input_data)
    
    def tick(self) -> Optional[Frame]:
        """
        帧引擎时钟周期
        
        尝试推进到下一帧。如果当前帧的所有输入都已到齐，
        则返回该帧并将 current_frame 加 1。
        
        Returns:
            如果有完整帧可执行则返回 Frame，否则返回 None
        """
        # 尝试提交当前帧
        frame = self.frame_buffer.try_commit_frame(
            self.current_frame, 
            self.player_count
        )
        
        if frame:
            self.frame_history[frame.frame_id] = frame
            
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
        强制推进帧（超时处理）
        
        当某些玩家输入长时间未到时，强制生成一个帧，
        缺失的玩家输入用空数据填充。
        
        Returns:
            强制生成的 Frame（confirmed=False）
        """
        # 获取已收集的输入
        pending = self.frame_buffer.pending_inputs.get(self.current_frame, {})
        
        # 填充缺失的玩家输入（使用空输入）
        for player_id in range(self.player_count):
            if player_id not in pending:
                pending[player_id] = b''
        
        frame = Frame(
            frame_id=self.current_frame,
            inputs=dict(pending),
            confirmed=False
        )
        
        self.frame_history[frame.frame_id] = frame
        
        # 清理旧历史
        oldest = self.current_frame - self.max_history
        for fid in list(self.frame_history.keys()):
            if fid < oldest:
                del self.frame_history[fid]
        
        # 清理 pending
        if self.current_frame in self.frame_buffer.pending_inputs:
            del self.frame_buffer.pending_inputs[self.current_frame]
        
        self.current_frame += 1
        return frame
    
    def get_frame(self, frame_id: int) -> Optional[Frame]:
        """
        获取历史帧
        
        Args:
            frame_id: 要查询的帧ID
        
        Returns:
            Frame 对象，不存在则返回 None
        """
        return self.frame_history.get(frame_id)
    
    def get_current_frame_id(self) -> int:
        """
        获取当前帧ID
        
        Returns:
            当前正在等待的帧ID
        """
        return self.current_frame
    
    def get_stats(self) -> dict:
        """
        获取引擎统计信息
        
        Returns:
            包含统计数据的字典
        """
        return {
            'current_frame': self.current_frame,
            'player_count': self.player_count,
            'buffer_size': self.buffer_size,
            'history_size': len(self.frame_history),
            **self.frame_buffer.get_buffer_status()
        }
