"""
Integration tests for frame synchronization
"""

import pytest
import asyncio
import time
from typing import List, Dict
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.frame import FrameEngine, Frame, FrameBuffer
from core.input import PlayerInput, InputFlags, InputManager, InputValidator
from core.physics import PhysicsEngine, Entity
from core.state import GameState, StateValidator
from core.rng import DeterministicRNG
from server.main import GameServer, RateLimiter, MessageValidator
from client.game_client import GameClient
from client.predictor import ClientPredictor


# ==================== 帧同步集成测试 ====================

class TestFrameSyncIntegration:
    """帧同步集成测试"""
    
    def test_full_frame_cycle(self):
        """测试完整帧周期"""
        # 1. 创建帧引擎
        engine = FrameEngine(player_count=2, buffer_size=2)
        
        # 2. 模拟多帧
        for frame_id in range(10):
            # 收集输入
            for player_id in range(2):
                input_data = PlayerInput(
                    frame_id=frame_id,
                    player_id=player_id,
                    flags=InputFlags.MOVE_RIGHT if player_id == 0 else InputFlags.MOVE_LEFT
                ).serialize()
                engine.add_input(frame_id, player_id, input_data)
            
            # 执行帧
            frame = engine.tick()
            
            # 验证
            assert frame is not None
            assert frame.confirmed
            assert len(frame.inputs) == 2
        
        # 3. 验证历史
        assert engine.get_current_frame_id() == 10
    
    def test_state_synchronization_between_clients(self):
        """测试客户端间状态同步"""
        # 创建两个独立的游戏状态
        state1 = GameState()
        state2 = GameState()
        physics1 = PhysicsEngine()
        physics2 = PhysicsEngine()
        
        # 添加相同初始状态的实体
        for i in range(4):
            e1 = Entity.from_float(i, 100.0 * (i + 1), 200.0)
            e2 = Entity.from_float(i, 100.0 * (i + 1), 200.0)
            
            state1.add_entity(e1)
            state2.add_entity(e2)
            physics1.add_entity(e1)
            physics2.add_entity(e2)
        
        # 模拟相同输入
        for frame in range(100):
            for i in range(4):
                # 相同输入
                flags = InputFlags.MOVE_RIGHT if i % 2 == 0 else InputFlags.MOVE_LEFT
                physics1.apply_input(i, flags, 300 << 16)
                physics2.apply_input(i, flags, 300 << 16)
            
            physics1.update(33)
            physics2.update(33)
        
        # 验证状态一致
        for i in range(4):
            e1 = state1.get_entity(i)
            e2 = state2.get_entity(i)
            assert e1.x == e2.x, f"Entity {i} x mismatch: {e1.x} != {e2.x}"
            assert e1.y == e2.y, f"Entity {i} y mismatch: {e1.y} != {e2.y}"


class TestClientPredictionIntegration:
    """客户端预测集成测试"""
    
    def test_prediction_and_rollback(self):
        """测试预测和回滚"""
        # 创建游戏状态和预测器
        game_state = GameState()
        physics = PhysicsEngine()
        
        # 添加玩家实体
        player = Entity.from_float(1, 100.0, 200.0)
        game_state.add_entity(player)
        game_state.bind_player_entity(0, 1)
        physics.add_entity(player)
        
        predictor = ClientPredictor(game_state, physics, player_id=0)
        
        # 模拟预测
        my_input = PlayerInput(
            frame_id=1,
            player_id=0,
            flags=InputFlags.MOVE_RIGHT
        ).serialize()
        
        predictor.predict_frame(1, my_input, other_players=[1])
        
        # 验证预测计数
        assert predictor.prediction_count == 1
        
        # 模拟服务器帧（预测正确）
        server_frame = Frame(
            frame_id=1,
            inputs={0: my_input, 1: b''},
            confirmed=True
        )
        
        result = predictor.on_server_frame(server_frame, other_players=[1])
        
        assert result.predicted
        assert result.correct
        assert not result.rollback_needed
    
    def test_prediction_accuracy_tracking(self):
        """测试预测准确率追踪"""
        game_state = GameState()
        physics = PhysicsEngine()
        
        player = Entity.from_float(1, 100.0, 200.0)
        game_state.add_entity(player)
        game_state.bind_player_entity(0, 1)
        physics.add_entity(player)
        
        predictor = ClientPredictor(game_state, physics, player_id=0)
        
        # 执行多次预测
        for i in range(10):
            my_input = PlayerInput(frame_id=i, player_id=0, flags=InputFlags.MOVE_RIGHT).serialize()
            predictor.predict_frame(i, my_input, other_players=[1])
        
        # 模拟服务器帧（一半正确，一半错误）
        for i in range(10):
            my_input = PlayerInput(frame_id=i, player_id=0, flags=InputFlags.MOVE_RIGHT).serialize()
            
            # 偶数帧正确，奇数帧错误
            if i % 2 == 0:
                server_inputs = {0: my_input, 1: b''}
            else:
                server_inputs = {0: my_input, 1: PlayerInput(frame_id=i, player_id=1, flags=InputFlags.MOVE_LEFT).serialize()}
            
            server_frame = Frame(frame_id=i, inputs=server_inputs, confirmed=True)
            predictor.on_server_frame(server_frame, other_players=[1])
        
        # 验证统计
        stats = predictor.get_stats()
        assert stats['prediction_count'] == 10


class TestReplayIntegration:
    """回放系统集成测试"""
    
    def test_record_and_playback(self):
        """测试录制和回放"""
        from core.replay import ReplayRecorder, ReplayPlayer
        
        # 创建录制器
        recorder = ReplayRecorder(player_count=2, seed=12345)
        recorder.start_recording(player_ids=[0, 1])
        
        # 录制帧
        for i in range(100):
            inputs = {
                0: PlayerInput(frame_id=i, player_id=0, flags=InputFlags.MOVE_RIGHT).serialize(),
                1: PlayerInput(frame_id=i, player_id=1, flags=InputFlags.MOVE_LEFT).serialize()
            }
            recorder.record_frame(i, inputs)
        
        recorder.stop_recording()
        
        # 保存和加载
        filename = '/tmp/test_replay.fsrp'
        recorder.save(filename)
        
        loaded = ReplayRecorder.load(filename)
        
        # 验证
        assert loaded.header.player_count == 2
        assert loaded.header.frame_count == 100
        assert len(loaded.frames) == 100
        
        # 播放
        player = ReplayPlayer(loaded)
        player.play()
        
        frames_played = 0
        while True:
            frame = player.get_next_frame()
            if frame is None:
                break
            frames_played += 1
        
        assert frames_played == 100
        
        # 清理
        os.remove(filename)
    
    def test_replay_seek(self):
        """测试回放跳转"""
        from core.replay import ReplayRecorder, ReplayPlayer
        
        recorder = ReplayRecorder(player_count=2)
        recorder.start_recording(player_ids=[0, 1])
        
        for i in range(100):
            inputs = {0: b'input', 1: b'input'}
            recorder.record_frame(i, inputs)
        
        recorder.stop_recording()
        
        player = ReplayPlayer(recorder)
        player.play()  # 需要开始播放才能获取帧
        
        # 跳转到帧50
        assert player.seek_to_frame(50)
        
        # 获取下一帧应该是50或之后
        frame = player.get_next_frame()
        assert frame.frame_id >= 50


class TestNetworkIntegration:
    """网络集成测试"""
    
    def test_rate_limiter(self):
        """测试速率限制器"""
        limiter = RateLimiter(max_requests=10, window=1.0)
        
        player_id = "test_player"
        
        # 前10次应该允许
        for _ in range(10):
            assert limiter.is_allowed(player_id)
        
        # 第11次应该拒绝
        assert not limiter.is_allowed(player_id)
    
    def test_message_validator(self):
        """测试消息验证器"""
        import msgpack
        
        # 有效消息
        valid_msg = msgpack.packb({
            'type': 'input',
            'payload': {'frame_id': 1}
        })
        assert MessageValidator.validate(valid_msg) is not None
        
        # 无效类型
        invalid_type = msgpack.packb({
            'type': 'invalid',
            'payload': {}
        })
        assert MessageValidator.validate(invalid_type) is None
        
        # 过大消息
        large_msg = b'\x00' * 20000
        assert MessageValidator.validate(large_msg) is None


class TestDeterminismIntegration:
    """确定性集成测试"""
    
    def test_cross_platform_determinism(self):
        """测试跨平台确定性"""
        # 模拟两个不同平台的客户端
        
        # 客户端1
        rng1 = DeterministicRNG(12345)
        physics1 = PhysicsEngine()
        entity1 = Entity.from_float(1, 100.0, 100.0)
        entity1.vx = 200 << 16
        physics1.add_entity(entity1)
        
        # 客户端2
        rng2 = DeterministicRNG(12345)
        physics2 = PhysicsEngine()
        entity2 = Entity.from_float(1, 100.0, 100.0)
        entity2.vx = 200 << 16
        physics2.add_entity(entity2)
        
        # 执行相同操作
        for _ in range(100):
            # 随机数一致
            r1 = rng1.range(0, 100)
            r2 = rng2.range(0, 100)
            assert r1 == r2
            
            # 物理一致
            physics1.update(33)
            physics2.update(33)
        
        # 验证最终状态一致
        assert entity1.x == entity2.x
        assert entity1.y == entity2.y
    
    def test_state_hash_consistency(self):
        """测试状态哈希一致性"""
        # 两个相同状态
        state1 = GameState()
        state2 = GameState()
        
        for i in range(5):
            e1 = Entity.from_float(i, 100.0 * i, 200.0 * i)
            e2 = Entity.from_float(i, 100.0 * i, 200.0 * i)
            state1.add_entity(e1)
            state2.add_entity(e2)
        
        state1.frame_id = 100
        state2.frame_id = 100
        
        hash1 = state1.compute_state_hash()
        hash2 = state2.compute_state_hash()
        
        assert hash1 == hash2
        
        # 修改状态后哈希应该不同
        state1.frame_id = 101
        hash3 = state1.compute_state_hash()
        assert hash1 != hash3


class TestSecurityIntegration:
    """安全性集成测试"""
    
    def test_input_validation_integration(self):
        """测试输入验证集成"""
        validator = InputValidator(max_apm=600)
        
        # 正常输入
        for _ in range(50):
            input_data = PlayerInput(
                frame_id=1,
                player_id=1,
                flags=InputFlags.MOVE_RIGHT
            )
            assert validator.validate(1, input_data)
        
        # 帧ID验证
        assert validator.validate_frame_id(100, 100)
        assert validator.validate_frame_id(150, 100)
        assert not validator.validate_frame_id(-1, 100)
        assert not validator.validate_frame_id(300, 100)
    
    def test_replay_attack_prevention(self):
        """测试重放攻击防护"""
        # 模拟服务器端的重放检测
        processed_frames = set()
        
        def is_replay(frame_id: int, player_id: int) -> bool:
            key = (frame_id, player_id)
            if key in processed_frames:
                return True
            processed_frames.add(key)
            return False
        
        # 第一次不是重放
        assert not is_replay(1, 1)
        
        # 第二次是重放
        assert is_replay(1, 1)
        
        # 不同帧不是重放
        assert not is_replay(2, 1)


# ==================== 性能测试 ====================

class TestPerformance:
    """性能测试"""
    
    def test_physics_performance(self):
        """测试物理性能"""
        import time
        
        physics = PhysicsEngine()
        
        # 创建100个实体
        for i in range(100):
            entity = Entity.from_float(i, i * 10.0, i * 10.0)
            physics.add_entity(entity)
        
        # 测量100帧的执行时间
        start = time.time()
        for _ in range(100):
            physics.update(33)
        elapsed = time.time() - start
        
        # 应该在合理时间内完成
        assert elapsed < 1.0  # 1秒内完成100帧
    
    def test_frame_engine_throughput(self):
        """测试帧引擎吞吐量"""
        import time
        
        engine = FrameEngine(player_count=4)
        
        start = time.time()
        frames = 0
        
        while frames < 1000:
            for player_id in range(4):
                engine.add_input(frames, player_id, b'input')
            
            frame = engine.tick()
            if frame:
                frames += 1
        
        elapsed = time.time() - start
        throughput = frames / elapsed
        
        # 应该能达到高吞吐量
        assert throughput > 1000  # 每秒至少1000帧


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
