#!/usr/bin/env python3
"""
Debugging tools for frame synchronization
"""

import json
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import hashlib

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.frame import Frame
from core.state import GameState
from core.physics import Entity


@dataclass
class DebugLog:
    """调试日志条目"""
    frame_id: int
    event: str
    data: dict
    timestamp: float
    state_hash: str


class FrameSyncDebugger:
    """
    帧同步调试器
    
    功能：
    1. 状态对比
    2. 分歧检测
    3. 帧时间线可视化
    4. 调试日志导出
    """
    
    def __init__(self):
        self.logs: List[DebugLog] = []
        self.state_history: Dict[int, dict] = {}
        self.divergence_points: List[int] = []
    
    def log(self, frame_id: int, event: str, data: dict, state: GameState = None):
        """
        记录调试日志
        
        Args:
            frame_id: 帧ID
            event: 事件名称
            data: 事件数据
            state: 游戏状态（可选）
        """
        state_hash = ""
        if state:
            state_hash = state.compute_state_hash()
            self.state_history[frame_id] = self._capture_state(state)
        
        log_entry = DebugLog(
            frame_id=frame_id,
            event=event,
            data=data,
            timestamp=time.time(),
            state_hash=state_hash
        )
        
        self.logs.append(log_entry)
    
    def compare_states(self, state1: GameState, state2: GameState) -> Dict:
        """
        对比两个游戏状态
        
        Returns:
            差异报告
        """
        diff = {
            'frame_id_diff': state1.frame_id != state2.frame_id,
            'entity_count_diff': len(state1.entities) != len(state2.entities),
            'entity_diffs': [],
            'hash_match': False
        }
        
        # 比较哈希
        hash1 = state1.compute_state_hash()
        hash2 = state2.compute_state_hash()
        diff['hash_match'] = hash1 == hash2
        diff['hash1'] = hash1
        diff['hash2'] = hash2
        
        # 比较实体
        all_entity_ids = set(state1.entities.keys()) | set(state2.entities.keys())
        
        for eid in all_entity_ids:
            e1 = state1.get_entity(eid)
            e2 = state2.get_entity(eid)
            
            if e1 is None:
                diff['entity_diffs'].append({
                    'entity_id': eid,
                    'type': 'missing_in_state1'
                })
            elif e2 is None:
                diff['entity_diffs'].append({
                    'entity_id': eid,
                    'type': 'missing_in_state2'
                })
            else:
                entity_diff = self._compare_entities(e1, e2)
                if entity_diff:
                    entity_diff['entity_id'] = eid
                    diff['entity_diffs'].append(entity_diff)
        
        return diff
    
    def _compare_entities(self, e1: Entity, e2: Entity) -> Optional[dict]:
        """比较两个实体"""
        diff = {}
        
        if e1.x != e2.x:
            diff['x_diff'] = {'state1': e1.x, 'state2': e2.x}
        if e1.y != e2.y:
            diff['y_diff'] = {'state1': e1.y, 'state2': e2.y}
        if e1.vx != e2.vx:
            diff['vx_diff'] = {'state1': e1.vx, 'state2': e2.vx}
        if e1.vy != e2.vy:
            diff['vy_diff'] = {'state1': e1.vy, 'state2': e2.vy}
        if e1.hp != e2.hp:
            diff['hp_diff'] = {'state1': e1.hp, 'state2': e2.hp}
        
        return diff if diff else None
    
    def find_divergence_point(self, history1: Dict[int, str], history2: Dict[int, str]) -> Optional[int]:
        """
        找到状态分歧点
        
        Args:
            history1: 客户端1的状态哈希历史 {frame_id: hash}
            history2: 客户端2的状态哈希历史
        
        Returns:
            分歧帧ID，如果完全一致返回 None
        """
        common_frames = sorted(set(history1.keys()) & set(history2.keys()))
        
        for frame_id in common_frames:
            if history1[frame_id] != history2[frame_id]:
                self.divergence_points.append(frame_id)
                return frame_id
        
        return None
    
    def visualize_frame_timeline(self, frames: List[Frame], output_file: str = None) -> str:
        """
        可视化帧时间线
        
        Args:
            frames: 帧列表
            output_file: 输出文件路径（可选）
        
        Returns:
            ASCII 可视化字符串
        """
        if not frames:
            return "No frames to visualize"
        
        lines = []
        lines.append("=" * 80)
        lines.append("Frame Timeline")
        lines.append("=" * 80)
        
        for frame in frames[:50]:  # 只显示前50帧
            frame_str = f"Frame {frame.frame_id:4d} | "
            
            # 显示输入状态
            player_inputs = []
            for player_id in sorted(frame.inputs.keys()):
                input_data = frame.inputs[player_id]
                input_str = "X" if input_data else "_"
                player_inputs.append(f"P{player_id}:{input_str}")
            
            frame_str += " ".join(player_inputs)
            
            # 确认状态
            frame_str += f" | {'CONFIRMED' if frame.confirmed else 'PENDING'}"
            
            lines.append(frame_str)
        
        if len(frames) > 50:
            lines.append(f"... and {len(frames) - 50} more frames")
        
        result = "\n".join(lines)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(result)
        
        return result
    
    def export_debug_log(self, filename: str):
        """
        导出调试日志
        
        Args:
            filename: 输出文件名
        """
        data = {
            'logs': [asdict(log) for log in self.logs],
            'divergence_points': self.divergence_points,
            'export_time': time.time()
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def _capture_state(self, state: GameState) -> dict:
        """捕获状态快照"""
        entities = {}
        for eid, entity in state.entities.items():
            entities[eid] = {
                'x': entity.x,
                'y': entity.y,
                'vx': entity.vx,
                'vy': entity.vy,
                'hp': entity.hp
            }
        
        return {
            'frame_id': state.frame_id,
            'entities': entities
        }
    
    def get_stats(self) -> dict:
        """获取调试统计"""
        return {
            'log_count': len(self.logs),
            'state_snapshots': len(self.state_history),
            'divergence_count': len(self.divergence_points),
            'events': list(set(log.event for log in self.logs))
        }


class InputAnalyzer:
    """输入分析器"""
    
    def __init__(self):
        self.input_history: Dict[int, List[dict]] = {}  # {player_id: [inputs]}
    
    def record_input(self, player_id: int, frame_id: int, input_flags: int):
        """记录输入"""
        if player_id not in self.input_history:
            self.input_history[player_id] = []
        
        self.input_history[player_id].append({
            'frame_id': frame_id,
            'flags': input_flags,
            'timestamp': time.time()
        })
    
    def get_input_frequency(self, player_id: int) -> dict:
        """获取输入频率"""
        if player_id not in self.input_history:
            return {}
        
        inputs = self.input_history[player_id]
        if len(inputs) < 2:
            return {'frequency': 0}
        
        # 计算输入间隔
        intervals = []
        for i in range(1, len(inputs)):
            dt = inputs[i]['timestamp'] - inputs[i-1]['timestamp']
            intervals.append(dt)
        
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        
        return {
            'total_inputs': len(inputs),
            'avg_interval_ms': avg_interval * 1000,
            'frequency': 1 / avg_interval if avg_interval > 0 else 0
        }
    
    def detect_suspicious_patterns(self, player_id: int) -> List[str]:
        """检测可疑输入模式"""
        suspicious = []
        
        if player_id not in self.input_history:
            return suspicious
        
        inputs = self.input_history[player_id]
        
        # 检测超高频率输入
        freq = self.get_input_frequency(player_id)
        if freq.get('frequency', 0) > 30:  # 超过30次/秒
            suspicious.append(f"High input frequency: {freq['frequency']:.1f}/sec")
        
        # 检测重复输入
        if len(inputs) > 10:
            recent_flags = [i['flags'] for i in inputs[-10:]]
            if len(set(recent_flags)) == 1:
                suspicious.append("Repeated identical inputs")
        
        return suspicious


class NetworkMonitor:
    """网络监控器"""
    
    def __init__(self):
        self.latency_history: List[float] = []
        self.packet_loss_count = 0
        self.total_packets = 0
    
    def record_latency(self, latency_ms: float):
        """记录延迟"""
        self.latency_history.append(latency_ms)
        self.total_packets += 1
        
        # 只保留最近1000条
        if len(self.latency_history) > 1000:
            self.latency_history.pop(0)
    
    def record_packet_loss(self):
        """记录丢包"""
        self.packet_loss_count += 1
        self.total_packets += 1
    
    def get_stats(self) -> dict:
        """获取网络统计"""
        if not self.latency_history:
            return {
                'avg_latency': 0,
                'min_latency': 0,
                'max_latency': 0,
                'packet_loss_rate': 0
            }
        
        return {
            'avg_latency': sum(self.latency_history) / len(self.latency_history),
            'min_latency': min(self.latency_history),
            'max_latency': max(self.latency_history),
            'p99_latency': sorted(self.latency_history)[int(len(self.latency_history) * 0.99)],
            'packet_loss_rate': self.packet_loss_count / self.total_packets if self.total_packets > 0 else 0,
            'total_packets': self.total_packets
        }


# ==================== 命令行工具 ====================

def main():
    """调试工具命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Frame Sync Debug Tools')
    parser.add_argument('command', choices=['compare', 'analyze', 'visualize'],
                       help='Command to run')
    parser.add_argument('--file1', help='First state file')
    parser.add_argument('--file2', help='Second state file')
    parser.add_argument('--output', '-o', help='Output file')
    
    args = parser.parse_args()
    
    if args.command == 'compare':
        if not args.file1 or not args.file2:
            print("Error: --file1 and --file2 required for compare")
            return
        
        with open(args.file1) as f:
            state1_data = json.load(f)
        with open(args.file2) as f:
            state2_data = json.load(f)
        
        # 简单比较
        hash1 = hashlib.md5(json.dumps(state1_data, sort_keys=True).encode()).hexdigest()
        hash2 = hashlib.md5(json.dumps(state2_data, sort_keys=True).encode()).hexdigest()
        
        print(f"State 1 hash: {hash1}")
        print(f"State 2 hash: {hash2}")
        print(f"Match: {hash1 == hash2}")
    
    elif args.command == 'visualize':
        print("Use the visualize_frame_timeline method in code")


if __name__ == '__main__':
    main()
