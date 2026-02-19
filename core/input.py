"""
输入处理模块

本模块处理帧同步中的玩家输入：
- InputFlags: 输入标志位枚举（移动、攻击等）
- PlayerInput: 玩家输入数据结构，支持序列化
- InputManager: 输入管理器，负责收集和缓存输入
- InputValidator: 输入验证器，防止作弊
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union
from enum import IntFlag
import struct


class InputFlags(IntFlag):
    """
    输入标志位枚举
    
    使用位标志来表示玩家的各种输入操作。
    多个标志可以组合使用（例如：同时移动和攻击）。
    
    位运算示例:
        # 组合多个标志
        flags = InputFlags.MOVE_RIGHT | InputFlags.ATTACK
        
        # 检查是否包含某个标志
        if flags & InputFlags.ATTACK:
            print("玩家正在攻击")
        
        # 移除某个标志
        flags &= ~InputFlags.ATTACK
    
    属性:
        NONE (0x00): 无操作
        MOVE_UP (0x01): 向上移动（对应按键：W / ↑）
        MOVE_DOWN (0x02): 向下移动（对应按键：S / ↓）
        MOVE_LEFT (0x04): 向左移动（对应按键：A / ←）
        MOVE_RIGHT (0x08): 向右移动（对应按键：D / →）
        ATTACK (0x10): 普通攻击（对应按键：空格 / 回车）
        SKILL_1 (0x20): 技能1
        SKILL_2 (0x40): 技能2
        JUMP (0x80): 跳跃
    """
    NONE = 0
    MOVE_UP = 1 << 0       # 0x01 = 1
    MOVE_DOWN = 1 << 1     # 0x02 = 2
    MOVE_LEFT = 1 << 2     # 0x04 = 4
    MOVE_RIGHT = 1 << 3    # 0x08 = 8
    ATTACK = 1 << 4        # 0x10 = 16
    SKILL_1 = 1 << 5       # 0x20 = 32
    SKILL_2 = 1 << 6       # 0x40 = 64
    JUMP = 1 << 7          # 0x80 = 128


@dataclass
class PlayerInput:
    """
    玩家输入数据结构
    
    表示一个玩家在某一帧的完整输入，支持紧凑的二进制序列化。
    
    序列化格式（共16字节）:
        - frame_id: 4字节无符号整数
        - player_id: 2字节无符号整数
        - flags: 1字节标志位
        - target_x: 4字节有符号整数（定点数）
        - target_y: 4字节有符号整数（定点数）
        - extra_len: 1字节额外数据长度
        - extra: 变长额外数据
    
    属性:
        frame_id (int): 
            该输入对应的帧ID。
            用于确保输入在正确的帧被执行。
            例如：frame_id=100 表示这是第100帧的输入。
        
        player_id (int): 
            发送该输入的玩家ID。
            范围：0 到 player_count-1。
        
        flags (int): 
            输入标志位（InputFlags 的组合）。
            例如：flags=0x18 表示同时按下右移和攻击。
        
        target_x (int): 
            目标X坐标（定点数 16.16 格式）。
            用于指向性技能或移动目标。
            例如：target_x = 500 * 65536 = 32768000
        
        target_y (int): 
            目标Y坐标（定点数 16.16 格式）。
        
        extra (bytes): 
            额外数据（最多255字节）。
            用于扩展功能，如自定义技能参数。
    """
    frame_id: int
    player_id: int
    flags: int = 0
    target_x: int = 0
    target_y: int = 0
    extra: bytes = b''
    
    # 序列化格式: frame_id(4) + player_id(2) + flags(1) + target_x(4) + target_y(4) + extra_len(1) + extra
    FORMAT = '!IHBiiB'
    
    def set_flag(self, flag: InputFlags):
        """
        设置输入标志
        
        Args:
            flag: 要设置的标志（可组合多个）
        """
        self.flags |= flag
    
    def has_flag(self, flag: InputFlags) -> bool:
        """
        检查是否包含某个标志
        
        Args:
            flag: 要检查的标志
        
        Returns:
            True 如果包含该标志
        """
        return bool(self.flags & flag)
    
    def clear_flag(self, flag: InputFlags):
        """
        清除某个标志
        
        Args:
            flag: 要清除的标志
        """
        self.flags &= ~flag
    
    def serialize(self) -> bytes:
        """
        序列化为二进制（网络传输用）
        
        Returns:
            16+ 字节的二进制数据
        """
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
        """
        从二进制反序列化
        
        Args:
            data: 二进制数据
        
        Returns:
            PlayerInput 实例
        
        Raises:
            ValueError: 如果数据长度不足
        """
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
        """
        获取移动方向向量
        
        Returns:
            (dx, dy) 元组，每个值为 -1, 0, 或 1
        """
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
    
    负责收集、缓存和管理单个玩家的输入。
    每个玩家应该有一个独立的 InputManager 实例。
    
    工作流程:
        1. begin_frame(frame_id) - 开始新一帧的输入收集
        2. set_input(flags, x, y) - 设置当前帧的输入
        3. end_frame() - 结束输入收集，返回 PlayerInput
        4. send_input() - 将输入发送给服务器
    
    属性:
        player_id (int): 
            该管理器对应的玩家ID。
        
        current_input (PlayerInput): 
            当前帧正在收集的输入。
            begin_frame() 时创建，end_frame() 时清空。
        
        input_history (Dict[int, bytes]): 
            历史输入记录（序列化后的字节）。
            键为 frame_id，用于重发和回滚。
            例如：{100: b'\\x00...', 101: b'\\x00...'}
        
        parsed_history (Dict[int, PlayerInput]): 
            解析后的本地输入历史。
            仅存储本地玩家的输入，用于预测校验。
        
        max_history (int): 
            最大历史记录数量。
            默认 300 帧，超过后自动清理旧记录。
        
        pending_inputs (List[PlayerInput]): 
            待发送的输入队列。
            end_frame() 时添加，get_pending_inputs() 时取出。
    """
    
    def __init__(self, player_id: int):
        """
        初始化输入管理器
        
        Args:
            player_id: 玩家ID
        """
        self.player_id = player_id
        self.current_input: Optional[PlayerInput] = None
        self.input_history: Dict[int, bytes] = {}
        self.parsed_history: Dict[int, PlayerInput] = {}
        self.max_history = 300
        self.pending_inputs: List[PlayerInput] = []
    
    def begin_frame(self, frame_id: int):
        """
        开始新帧的输入收集
        
        Args:
            frame_id: 新帧的ID
        """
        self.current_input = PlayerInput(
            frame_id=frame_id,
            player_id=self.player_id
        )
    
    def set_input(self, flags: int, target_x: int = 0, target_y: int = 0, extra: bytes = b''):
        """
        设置当前帧的输入
        
        Args:
            flags: 输入标志位
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
        结束当前帧的输入收集
        
        Returns:
            当前帧的 PlayerInput，如果没有开始帧则返回 None
        """
        if not self.current_input:
            return None
        
        # 保存到历史
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
            待发送输入列表（获取后队列清空）
        """
        inputs = self.pending_inputs.copy()
        self.pending_inputs.clear()
        return inputs
    
    def get_input(self, frame_id: int) -> Optional[bytes]:
        """
        获取指定帧的输入（序列化格式）
        
        Args:
            frame_id: 帧ID
        
        Returns:
            序列化后的输入字节，不存在则返回 None
        """
        return self.input_history.get(frame_id)
    
    def get_parsed_input(self, frame_id: int) -> Optional[PlayerInput]:
        """
        获取解析后的输入（仅本地玩家）
        
        Args:
            frame_id: 帧ID
        
        Returns:
            PlayerInput 对象
        """
        return self.parsed_history.get(frame_id)
    
    def apply_remote_input(self, player_id: int, frame_id: int, input_data: bytes):
        """
        应用远程玩家的输入
        
        Args:
            player_id: 远程玩家ID
            frame_id: 帧ID
            input_data: 序列化的输入数据
        """
        key = (frame_id, player_id)
        self.input_history[key] = input_data


class InputValidator:
    """
    输入验证器
    
    用于检测异常输入（可能表示作弊）。
    应该在服务器端使用，验证客户端发来的输入。
    
    检测项目:
    1. 输入大小是否超限
    2. 帧ID是否合法（不超前太多）
    3. 坐标是否在有效范围内
    4. 输入频率是否异常（超高速点击）
    
    属性:
        max_apm (int): 
            每分钟最大操作数（Actions Per Minute）。
            用于检测自动化脚本/外挂。
            默认 600，超过人类极限（职业玩家约 300-400）。
        
        input_times (Dict[int, List[float]]): 
            每个玩家的输入时间记录。
            键为 player_id，值为时间戳列表。
            用于 APM 检测。
    
    类常量:
        MAX_INPUT_SIZE (1024): 最大输入字节数
        MAX_FRAME_AHEAD (100): 最大超前帧数
    """
    
    MAX_INPUT_SIZE = 1024
    MAX_FRAME_AHEAD = 100
    
    def __init__(self, max_apm: int = 600):
        """
        初始化验证器
        
        Args:
            max_apm: 每分钟最大操作数
        """
        self.max_apm = max_apm
        self.input_times: Dict[int, List[float]] = {}
    
    def validate(self, player_id: int, input_data: Union[bytes, PlayerInput]) -> bool:
        """
        验证输入是否合法
        
        Args:
            player_id: 玩家ID
            input_data: 输入数据（字节或 PlayerInput）
        
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
        
        # 检查输入频率（使用帧ID作为时间基准，30fps）
        if player_id not in self.input_times:
            self.input_times[player_id] = []
        
        frame_time = input_data.frame_id * 0.033  # 30fps
        
        # 避免重复记录同一帧
        if self.input_times[player_id] and self.input_times[player_id][-1] == frame_time:
            pass  # 同一帧的重复输入，跳过APM检测
        else:
            self.input_times[player_id].append(frame_time)
            
            # 只保留最近1秒
            self.input_times[player_id] = [
                t for t in self.input_times[player_id] if frame_time - t < 1.0
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
            current_frame: 当前服务器帧ID
        
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
        检查输入坐标范围是否合法
        
        Args:
            target_x: 目标X坐标（定点数）
            target_y: 目标Y坐标（定点数）
        
        Returns:
            True 如果范围合法
        """
        # 定点数范围检查 (假设地图 0-10000 像素)
        MAX_COORD = 10000 << 16
        if abs(target_x) > MAX_COORD or abs(target_y) > MAX_COORD:
            return False
        return True
