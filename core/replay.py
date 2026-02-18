"""
Replay recording and playback system
"""

import json
import time
import zlib
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class ReplayFrame:
    """回放帧数据"""
    frame_id: int
    inputs: Dict[int, bytes]  # {player_id: input_data}
    timestamp: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'f': self.frame_id,
            'i': {str(k): list(v) for k, v in self.inputs.items()},
            't': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ReplayFrame':
        return cls(
            frame_id=data['f'],
            inputs={int(k): bytes(v) for k, v in data['i'].items()},
            timestamp=data.get('t', 0.0)
        )


@dataclass
class ReplayHeader:
    """回放文件头"""
    version: str = "1.0"
    game_name: str = "frame-sync-game"
    player_count: int = 2
    player_ids: List[int] = field(default_factory=list)
    start_time: float = 0.0
    duration: float = 0.0
    frame_count: int = 0
    seed: int = 0
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ReplayHeader':
        return cls(**data)


class ReplayRecorder:
    """
    回放录制器
    
    只记录输入，不记录完整状态
    文件很小，适合长时间录制
    """
    
    def __init__(self, player_count: int = 2, seed: int = 0):
        """
        初始化录制器
        
        Args:
            player_count: 玩家数量
            seed: 随机种子
        """
        self.header = ReplayHeader(
            player_count=player_count,
            seed=seed,
            start_time=time.time()
        )
        self.frames: List[ReplayFrame] = []
        self.is_recording = False
        self.player_ids: List[int] = []
    
    def start_recording(self, player_ids: List[int], metadata: dict = None):
        """
        开始录制
        
        Args:
            player_ids: 玩家ID列表
            metadata: 额外元数据
        """
        self.player_ids = player_ids
        self.header.player_ids = player_ids
        self.header.start_time = time.time()
        self.header.metadata = metadata or {}
        self.frames.clear()
        self.is_recording = True
    
    def record_frame(self, frame_id: int, inputs: Dict[int, bytes]):
        """
        记录一帧
        
        Args:
            frame_id: 帧ID
            inputs: 玩家输入 {player_id: input_data}
        """
        if not self.is_recording:
            return
        
        replay_frame = ReplayFrame(
            frame_id=frame_id,
            inputs=inputs.copy(),
            timestamp=time.time()
        )
        self.frames.append(replay_frame)
    
    def stop_recording(self):
        """停止录制"""
        if self.frames:
            self.header.duration = self.frames[-1].timestamp - self.header.start_time
            self.header.frame_count = len(self.frames)
        self.is_recording = False
    
    def save(self, filename: str, compress: bool = True):
        """
        保存回放文件
        
        Args:
            filename: 文件名
            compress: 是否压缩
        """
        self.stop_recording()
        
        data = {
            'header': self.header.to_dict(),
            'frames': [f.to_dict() for f in self.frames]
        }
        
        json_data = json.dumps(data, separators=(',', ':')).encode('utf-8')
        
        if compress:
            json_data = zlib.compress(json_data, level=9)
        
        with open(filename, 'wb') as f:
            if compress:
                f.write(b'FSRP')  # Frame Sync Replay (compressed)
            else:
                f.write(b'FSRJ')  # Frame Sync Replay (JSON)
            f.write(json_data)
    
    @classmethod
    def load(cls, filename: str) -> 'ReplayRecorder':
        """
        加载回放文件
        
        Args:
            filename: 文件名
        
        Returns:
            ReplayRecorder 实例
        """
        with open(filename, 'rb') as f:
            magic = f.read(4)
            data = f.read()
        
        if magic == b'FSRP':
            data = zlib.decompress(data)
        elif magic != b'FSRJ':
            raise ValueError(f"Invalid replay file format: {magic}")
        
        parsed = json.loads(data.decode('utf-8'))
        
        recorder = cls()
        recorder.header = ReplayHeader.from_dict(parsed['header'])
        recorder.frames = [ReplayFrame.from_dict(f) for f in parsed['frames']]
        recorder.player_ids = recorder.header.player_ids
        
        return recorder
    
    def get_stats(self) -> dict:
        """获取录制统计"""
        return {
            'frame_count': len(self.frames),
            'duration': self.header.duration,
            'player_count': self.header.player_count,
            'file_size_estimate': len(json.dumps([f.to_dict() for f in self.frames]))
        }


class ReplayPlayer:
    """
    回放播放器
    
    用于回放录制的游戏
    """
    
    def __init__(self, recorder: ReplayRecorder):
        """
        初始化播放器
        
        Args:
            recorder: 录制器实例
        """
        self.recorder = recorder
        self.current_frame_index = 0
        self.is_playing = False
        self.playback_speed = 1.0
        self.on_frame_callback = None
        self.on_complete_callback = None
    
    @classmethod
    def from_file(cls, filename: str) -> 'ReplayPlayer':
        """从文件创建播放器"""
        recorder = ReplayRecorder.load(filename)
        return cls(recorder)
    
    def play(self):
        """开始播放"""
        self.current_frame_index = 0
        self.is_playing = True
    
    def pause(self):
        """暂停"""
        self.is_playing = False
    
    def resume(self):
        """恢复"""
        self.is_playing = True
    
    def stop(self):
        """停止"""
        self.is_playing = False
        self.current_frame_index = 0
    
    def get_next_frame(self) -> Optional[ReplayFrame]:
        """
        获取下一帧
        
        Returns:
            下一帧数据，如果结束返回 None
        """
        if not self.is_playing:
            return None
        
        if self.current_frame_index >= len(self.recorder.frames):
            self.is_playing = False
            if self.on_complete_callback:
                self.on_complete_callback()
            return None
        
        frame = self.recorder.frames[self.current_frame_index]
        self.current_frame_index += 1
        
        if self.on_frame_callback:
            self.on_frame_callback(frame)
        
        return frame
    
    def seek_to_frame(self, frame_id: int) -> bool:
        """
        跳转到指定帧
        
        Args:
            frame_id: 目标帧ID
        
        Returns:
            是否成功
        """
        for i, frame in enumerate(self.recorder.frames):
            if frame.frame_id >= frame_id:
                self.current_frame_index = i
                return True
        return False
    
    def seek_to_time(self, seconds: float) -> bool:
        """
        跳转到指定时间
        
        Args:
            seconds: 时间（秒）
        
        Returns:
            是否成功
        """
        target_time = self.recorder.header.start_time + seconds
        
        for i, frame in enumerate(self.recorder.frames):
            if frame.timestamp >= target_time:
                self.current_frame_index = i
                return True
        return False
    
    def get_progress(self) -> float:
        """获取播放进度 (0.0 - 1.0)"""
        if not self.recorder.frames:
            return 0.0
        return self.current_frame_index / len(self.recorder.frames)
    
    def get_current_time(self) -> float:
        """获取当前播放时间"""
        if not self.recorder.frames or self.current_frame_index == 0:
            return 0.0
        
        frame = self.recorder.frames[self.current_frame_index - 1]
        return frame.timestamp - self.recorder.header.start_time
    
    def get_total_frames(self) -> int:
        """获取总帧数"""
        return len(self.recorder.frames)
    
    def on_frame(self, callback):
        """设置帧回调"""
        self.on_frame_callback = callback
    
    def on_complete(self, callback):
        """设置完成回调"""
        self.on_complete_callback = callback


class ReplayAnalyzer:
    """
    回放分析器
    
    用于分析回放数据
    """
    
    def __init__(self, recorder: ReplayRecorder):
        self.recorder = recorder
    
    def get_input_frequency(self, player_id: int) -> dict:
        """
        获取玩家输入频率
        
        Args:
            player_id: 玩家ID
        
        Returns:
            输入频率统计
        """
        input_count = 0
        empty_count = 0
        
        for frame in self.recorder.frames:
            if player_id in frame.inputs:
                if frame.inputs[player_id]:
                    input_count += 1
                else:
                    empty_count += 1
        
        return {
            'total_frames': len(self.recorder.frames),
            'input_frames': input_count,
            'empty_frames': empty_count,
            'input_rate': input_count / len(self.recorder.frames) if self.recorder.frames else 0
        }
    
    def get_frame_times(self) -> List[float]:
        """获取帧间隔时间"""
        if len(self.recorder.frames) < 2:
            return []
        
        times = []
        for i in range(1, len(self.recorder.frames)):
            dt = self.recorder.frames[i].timestamp - self.recorder.frames[i-1].timestamp
            times.append(dt)
        
        return times
    
    def get_average_frame_time(self) -> float:
        """获取平均帧时间"""
        times = self.get_frame_times()
        return sum(times) / len(times) if times else 0
    
    def detect_lag_frames(self, threshold: float = 0.1) -> List[int]:
        """
        检测延迟帧
        
        Args:
            threshold: 延迟阈值（秒）
        
        Returns:
            延迟帧ID列表
        """
        lag_frames = []
        times = self.get_frame_times()
        
        for i, dt in enumerate(times):
            if dt > threshold:
                lag_frames.append(self.recorder.frames[i].frame_id)
        
        return lag_frames
    
    def generate_report(self) -> dict:
        """生成分析报告"""
        player_stats = {}
        for player_id in self.recorder.player_ids:
            player_stats[player_id] = self.get_input_frequency(player_id)
        
        return {
            'header': self.recorder.header.to_dict(),
            'player_stats': player_stats,
            'average_frame_time': self.get_average_frame_time(),
            'lag_frames': len(self.detect_lag_frames()),
            'total_duration': self.recorder.header.duration
        }
