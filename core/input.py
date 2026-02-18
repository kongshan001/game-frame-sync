"""
Input handling for frame synchronization
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union
from enum import IntFlag
import struct


class InputFlags(IntFlag):
    """输入标志位"""
    NONE = 0
    MOVE_UP = 1 << 0
    MOVE_DOWN = 1 << 1
    MOVE_LEFT = 1 << 2
    MOVE_RIGHT = 1 << 3
    ATTACK = 1 << 4
    SKILL_1 = 1 << 5
    SKILL_2 = 1 << 6
    JUMP = 1 << 7


@dataclass
class PlayerInput:
    """
    玩家输入数据结构
    使用紧凑的二进制格式以减少网络传输
    """
    frame_id: int
    player_id: int
    flags: int = 0  # InputFlags
    target_x: int = 0  # 定点数 (16.16)
    target_y: int = 0
    extra: bytes = b''
    
    # 序列化格式: frame_id(4) + player_id(2) + flags(1) + target_x(4) + target_y(4) + extra_len(1) + extra
    FORMAT = '!IHBiiB'  # network byte order
    
    def set_flag(self, flag: InputFlags):
        """设置输入标志"""
        self.flags |= flag
    
    def has_flag(self, flag: InputFlags) -> bool:
        """检查是否有某标志"""
        return bool(self.flags & flag)
    
    def clear_flag(self, flag: InputFlags):
        """清除输入标志"""
        self.flags &= ~flag
    
    def serialize(self) -> bytes:
        """序列化为二进制"""
        header = struct.pack(
            self.FORMAT,
            self.frame_id,
            self.player_id,
            self.flags,
            self.target_x,
            self.target_y,
            len(self.extra)
        )
        return header + self.extra
    
    @classmethod
    def deserialize(cls, data: bytes) -> 'PlayerInput':
        """从二进制反序列化"""
        header_size = struct.calcsize(cls.FORMAT)
        
        if len(data) < header_size:
            raise ValueError("Input data too short")
        
        header = data[:header_size]
        extra = data[header_size:]
        
        frame_id, player_id, flags, target_x, target_y, extra_len = struct.unpack(
            cls.FORMAT, header
        )
        
        return cls(
            frame_id=frame_id,
            player_id=player_id,
            flags=flags,
            target_x=target_x,
            target_y=target_y,
            extra=extra[:extra_len]
        )
    
    def get_direction(self) -> tuple:
        """获取移动方向向量"""
        dx, dy = 0, 0
        if self.has_flag(InputFlags.MOVE_UP):
            dy = -1
        if self.has_flag(InputFlags.MOVE_DOWN):
            dy = 1
        if self.has_flag(InputFlags.MOVE_LEFT):
            dx = -1
        if self.has_flag(InputFlags.MOVE_RIGHT):
            dx = 1
        return (dx, dy)


class InputManager:
    """
    输入管理器
    负责收集、缓存和分发玩家输入
    """
    
    def __init__(self, player_id: int):
        """
        初始化输入管理器
        
        Args:
            player_id: 当前玩家ID
        """
        self.player_id = player_id
        self.current_input: Optional[PlayerInput] = None
        # 修复：统一使用 bytes 存储历史输入
        self.input_history: Dict[int, bytes] = {}
        self.parsed_history: Dict[int, PlayerInput] = {}  # 解析后的本地输入
        self.max_history = 300
        self.pending_inputs: List[PlayerInput] = []
    
    def begin_frame(self, frame_id: int):
        """
        开始新帧，创建输入对象
        
        Args:
            frame_id: 帧ID
        """
        self.current_input = PlayerInput(
            frame_id=frame_id,
            player_id=self.player_id
        )
    
    def set_input(self, flags: int, target_x: int = 0, target_y: int = 0, extra: bytes = b''):
        """
        设置当前帧输入
        
        Args:
            flags: 输入标志
            target_x: 目标X（定点数）
            target_y: 目标Y（定点数）
            extra: 额外数据
        """
        if self.current_input:
            self.current_input.flags = flags
            self.current_input.target_x = target_x
            self.current_input.target_y = target_y
            self.current_input.extra = extra
    
    def end_frame(self) -> Optional[PlayerInput]:
        """
        结束当前帧，返回输入数据
        
        Returns:
            当前帧的输入
        """
        if not self.current_input:
            return None
        
        # 保存到历史（bytes 格式，与其他玩家一致）
        serialized = self.current_input.serialize()
        self.input_history[self.current_input.frame_id] = serialized
        self.parsed_history[self.current_input.frame_id] = self.current_input
        
        # 清理旧历史
        if len(self.input_history) > self.max_history:
            oldest = min(self.input_history.keys())
            del self.input_history[oldest]
            if oldest in self.parsed_history:
                del self.parsed_history[oldest]
        
        # 加入待发送队列
        self.pending_inputs.append(self.current_input)
        
        result = self.current_input
        self.current_input = None
        return result
    
    def get_pending_inputs(self) -> List[PlayerInput]:
        """
        获取待发送的输入
        
        Returns:
            待发送输入列表
        """
        inputs = self.pending_inputs.copy()
        self.pending_inputs.clear()
        return inputs
    
    def get_input(self, frame_id: int) -> Optional[bytes]:
        """
        获取指定帧的输入（bytes格式）
        
        Args:
            frame_id: 帧ID
        
        Returns:
            输入数据，不存在则返回None
        """
        return self.input_history.get(frame_id)
    
    def get_parsed_input(self, frame_id: int) -> Optional[PlayerInput]:
        """
        获取解析后的输入（仅本地玩家）
        
        Args:
            frame_id: 帧ID
        
        Returns:
            解析后的输入
        """
        return self.parsed_history.get(frame_id)
    
    def apply_remote_input(self, player_id: int, frame_id: int, input_data: bytes):
        """
        应用远程玩家输入
        
        Args:
            player_id: 玩家ID
            frame_id: 帧ID
            input_data: 输入数据（序列化后）
        """
        # 修复：统一存储格式
        key = (frame_id, player_id)
        self.input_history[key] = input_data


class InputValidator:
    """
    输入验证器
    用于检测异常输入（可能表示作弊）
    """
    
    MAX_INPUT_SIZE = 1024  # 最大输入大小
    MAX_FRAME_AHEAD = 100  # 最大超前帧数
    
    def __init__(self, max_apm: int = 600):
        """
        初始化验证器
        
        Args:
            max_apm: 每分钟最大操作数
        """
        self.max_apm = max_apm
        self.input_times: Dict[int, List[float]] = {}  # {player_id: [timestamps]}
    
    def validate(self, player_id: int, input_data: Union[bytes, PlayerInput]) -> bool:
        """
        验证输入是否合法
        
        Args:
            player_id: 玩家ID
            input_data: 输入数据
        
        Returns:
            True 如果输入合法
        """
        # 如果是 bytes，先解析
        if isinstance(input_data, bytes):
            if len(input_data) > self.MAX_INPUT_SIZE:
                return False
            try:
                input_data = PlayerInput.deserialize(input_data)
            except ValueError:
                return False
        
        # 检查输入频率
        if player_id not in self.input_times:
            self.input_times[player_id] = []
        
        now = input_data.frame_id * 0.033  # 假设30fps
        self.input_times[player_id].append(now)
        
        # 只保留最近1秒
        self.input_times[player_id] = [
            t for t in self.input_times[player_id] if now - t < 1.0
        ]
        
        # 检查APM
        inputs_per_second = len(self.input_times[player_id])
        apm = inputs_per_second * 60
        
        if apm > self.max_apm:
            return False
        
        return True
    
    def validate_frame_id(self, frame_id: int, current_frame: int) -> bool:
        """
        验证帧ID是否合法
        
        Args:
            frame_id: 输入的帧ID
            current_frame: 当前帧ID
        
        Returns:
            True 如果帧ID合法
        """
        if frame_id < 0:
            return False
        if frame_id > current_frame + self.MAX_FRAME_AHEAD:
            return False
        return True
    
    def check_input_range(self, target_x: int, target_y: int) -> bool:
        """
        检查输入范围是否合法
        
        Args:
            target_x: 目标X坐标
            target_y: 目标Y坐标
        
        Returns:
            True 如果范围合法
        """
        # 定点数范围检查 (假设地图 0-10000 像素)
        MAX_COORD = 10000 << 16  # 定点数表示
        if abs(target_x) > MAX_COORD or abs(target_y) > MAX_COORD:
            return False
        return True
