#!/usr/bin/env python3
"""
Performance benchmarks for frame synchronization
"""

import time
import sys
import os
import json
from typing import List, Dict, Callable

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.frame import FrameEngine, Frame, FrameBuffer
from core.input import PlayerInput, InputFlags
from core.physics import PhysicsEngine, Entity
from core.state import GameState
from core.rng import DeterministicRNG


class Benchmark:
    """基准测试类"""
    
    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
        self.results: Dict = {}
    
    def start(self):
        """开始计时"""
        self._start_time = time.perf_counter()
    
    def stop(self):
        """停止计时"""
        elapsed = time.perf_counter() - self._start_time
        self.times.append(elapsed)
        return elapsed
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if not self.times:
            return {}
        
        total = sum(self.times)
        avg = total / len(self.times)
        min_t = min(self.times)
        max_t = max(self.times)
        
        # 计算百分位
        sorted_times = sorted(self.times)
        p50 = sorted_times[len(sorted_times) // 2]
        p99 = sorted_times[int(len(sorted_times) * 0.99)]
        
        return {
            'name': self.name,
            'iterations': len(self.times),
            'total_ms': total * 1000,
            'avg_ms': avg * 1000,
            'min_ms': min_t * 1000,
            'max_ms': max_t * 1000,
            'p50_ms': p50 * 1000,
            'p99_ms': p99 * 1000,
            'ops_per_sec': len(self.times) / total if total > 0 else 0
        }


def benchmark_collision_detection():
    """碰撞检测性能测试"""
    print("\n" + "=" * 50)
    print("Benchmark: Collision Detection")
    print("=" * 50)
    
    results = {}
    
    for entity_count in [10, 50, 100, 200]:
        physics = PhysicsEngine()
        
        # 创建实体
        for i in range(entity_count):
            x = (i % 10) * 50.0
            y = (i // 10) * 50.0
            entity = Entity.from_float(i, x, y)
            physics.add_entity(entity)
        
        # 基准测试
        bench = Benchmark(f"collision_{entity_count}")
        
        for _ in range(100):
            bench.start()
            physics.update(33)
            bench.stop()
        
        stats = bench.get_stats()
        results[entity_count] = stats
        
        print(f"\nEntities: {entity_count}")
        print(f"  Avg: {stats['avg_ms']:.3f}ms")
        print(f"  P99: {stats['p99_ms']:.3f}ms")
        print(f"  Ops/sec: {stats['ops_per_sec']:.0f}")
    
    return results


def benchmark_frame_throughput():
    """帧处理吞吐量测试"""
    print("\n" + "=" * 50)
    print("Benchmark: Frame Throughput")
    print("=" * 50)
    
    results = {}
    
    for player_count in [2, 4, 8]:
        engine = FrameEngine(player_count=player_count)
        
        bench = Benchmark(f"frame_{player_count}p")
        
        frame_id = 0
        while len(bench.times) < 1000:
            # 添加输入
            for player_id in range(player_count):
                input_data = PlayerInput(
                    frame_id=frame_id,
                    player_id=player_id,
                    flags=InputFlags.MOVE_RIGHT
                ).serialize()
                engine.add_input(frame_id, player_id, input_data)
            
            bench.start()
            frame = engine.tick()
            bench.stop()
            
            if frame:
                frame_id += 1
        
        stats = bench.get_stats()
        results[player_count] = stats
        
        print(f"\nPlayers: {player_count}")
        print(f"  Avg: {stats['avg_ms']:.3f}ms")
        print(f"  Throughput: {stats['ops_per_sec']:.0f} frames/sec")
    
    return results


def benchmark_serialization():
    """序列化性能测试"""
    print("\n" + "=" * 50)
    print("Benchmark: Serialization")
    print("=" * 50)
    
    results = {}
    
    # PlayerInput 序列化
    input_data = PlayerInput(
        frame_id=12345,
        player_id=1,
        flags=InputFlags.MOVE_RIGHT | InputFlags.ATTACK,
        target_x=500 << 16,
        target_y=300 << 16
    )
    
    bench_serialize = Benchmark("input_serialize")
    for _ in range(10000):
        bench_serialize.start()
        serialized = input_data.serialize()
        bench_serialize.stop()
    
    stats = bench_serialize.get_stats()
    results['input_serialize'] = stats
    print(f"\nInput Serialize: {stats['avg_ms']*1000:.3f}μs")
    
    # PlayerInput 反序列化
    bench_deserialize = Benchmark("input_deserialize")
    for _ in range(10000):
        bench_deserialize.start()
        restored = PlayerInput.deserialize(serialized)
        bench_deserialize.stop()
    
    stats = bench_deserialize.get_stats()
    results['input_deserialize'] = stats
    print(f"Input Deserialize: {stats['avg_ms']*1000:.3f}μs")
    
    # Entity 序列化
    entity = Entity.from_float(1, 100.5, 200.5)
    
    bench_entity_ser = Benchmark("entity_serialize")
    for _ in range(10000):
        bench_entity_ser.start()
        data = entity.serialize()
        bench_entity_ser.stop()
    
    stats = bench_entity_ser.get_stats()
    results['entity_serialize'] = stats
    print(f"Entity Serialize: {stats['avg_ms']*1000:.3f}μs")
    
    return results


def benchmark_state_hash():
    """状态哈希性能测试"""
    print("\n" + "=" * 50)
    print("Benchmark: State Hash")
    print("=" * 50)
    
    state = GameState()
    
    # 添加实体
    for i in range(50):
        entity = Entity.from_float(i, i * 10.0, i * 10.0)
        state.add_entity(entity)
    
    bench = Benchmark("state_hash")
    
    for _ in range(1000):
        bench.start()
        hash_value = state.compute_state_hash()
        bench.stop()
    
    stats = bench.get_stats()
    print(f"\nState Hash (50 entities):")
    print(f"  Avg: {stats['avg_ms']:.3f}ms")
    print(f"  P99: {stats['p99_ms']:.3f}ms")
    
    return stats


def benchmark_rng():
    """随机数生成性能测试"""
    print("\n" + "=" * 50)
    print("Benchmark: RNG")
    print("=" * 50)
    
    results = {}
    
    rng = DeterministicRNG(12345)
    
    # 整数随机数
    bench_int = Benchmark("rng_int")
    for _ in range(100000):
        bench_int.start()
        val = rng.range(0, 100)
        bench_int.stop()
    
    stats = bench_int.get_stats()
    results['rng_int'] = stats
    print(f"\nRNG Integer: {stats['avg_ms']*1000000:.3f}ns")
    
    # 浮点随机数
    bench_float = Benchmark("rng_float")
    for _ in range(100000):
        bench_float.start()
        val = rng.uniform()
        bench_float.stop()
    
    stats = bench_float.get_stats()
    results['rng_float'] = stats
    print(f"RNG Float: {stats['avg_ms']*1000000:.3f}ns")
    
    return results


def benchmark_memory():
    """内存使用测试"""
    print("\n" + "=" * 50)
    print("Benchmark: Memory Usage")
    print("=" * 50)
    
    try:
        import tracemalloc
    except ImportError:
        print("tracemalloc not available")
        return {}
    
    results = {}
    
    # 帧历史内存
    tracemalloc.start()
    
    engine = FrameEngine(player_count=4)
    for frame_id in range(1000):
        for player_id in range(4):
            engine.add_input(frame_id, player_id, b'input')
        engine.tick()
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    results['frame_history'] = {
        'current_mb': current / 1024 / 1024,
        'peak_mb': peak / 1024 / 1024
    }
    
    print(f"\nFrame History (1000 frames):")
    print(f"  Current: {current / 1024 / 1024:.2f} MB")
    print(f"  Peak: {peak / 1024 / 1024:.2f} MB")
    
    # 物理引擎内存
    tracemalloc.start()
    
    physics = PhysicsEngine()
    for i in range(1000):
        entity = Entity.from_float(i, i * 10.0, i * 10.0)
        physics.add_entity(entity)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    results['physics_entities'] = {
        'current_mb': current / 1024 / 1024,
        'peak_mb': peak / 1024 / 1024
    }
    
    print(f"\nPhysics (1000 entities):")
    print(f"  Current: {current / 1024 / 1024:.2f} MB")
    print(f"  Peak: {peak / 1024 / 1024:.2f} MB")
    
    return results


def run_all_benchmarks():
    """运行所有基准测试"""
    print("\n" + "=" * 60)
    print("  Frame Sync Performance Benchmarks")
    print("=" * 60)
    
    all_results = {}
    
    all_results['collision'] = benchmark_collision_detection()
    all_results['throughput'] = benchmark_frame_throughput()
    all_results['serialization'] = benchmark_serialization()
    all_results['state_hash'] = benchmark_state_hash()
    all_results['rng'] = benchmark_rng()
    all_results['memory'] = benchmark_memory()
    
    # 生成报告
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    
    # 提取关键指标
    if 'collision' in all_results:
        for count, stats in all_results['collision'].items():
            print(f"  Collision ({count} entities): {stats['avg_ms']:.3f}ms/frame")
    
    if 'throughput' in all_results:
        for count, stats in all_results['throughput'].items():
            print(f"  Throughput ({count} players): {stats['ops_per_sec']:.0f} frames/sec")
    
    # 保存结果
    report_path = '/tmp/benchmark_report.json'
    with open(report_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\nFull report saved to: {report_path}")
    
    return all_results


if __name__ == '__main__':
    run_all_benchmarks()
