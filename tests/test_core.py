"""
Unit tests for frame synchronization core
"""

import pytest
import time
from core.frame import Frame, FrameBuffer, FrameEngine
from core.input import PlayerInput, InputManager, InputFlags, InputValidator
from core.physics import Entity, PhysicsEngine, distance, EntityPool
from core.rng import DeterministicRNG
from core.state import GameState, StateSnapshot, StateValidator


# ==================== Frame 测试 ====================

class TestFrame:
    """Frame 测试"""
    
    def test_frame_creation(self):
        """测试帧创建"""
        frame = Frame(frame_id=1)
        
        assert frame.frame_id == 1
        assert frame.inputs == {}
        assert not frame.confirmed
    
    def test_frame_input(self):
        """测试帧输入"""
        frame = Frame(frame_id=1)
        
        frame.set_input(1, b'input1')
        frame.set_input(2, b'input2')
        
        assert frame.get_input(1) == b'input1'
        assert frame.get_input(2) == b'input2'
        assert frame.is_complete(2)
        assert not frame.is_complete(3)


class TestFrameBuffer:
    """FrameBuffer 测试"""
    
    def test_add_input(self):
        """测试添加输入"""
        buffer = FrameBuffer(buffer_size=2)
        
        buffer.add_input(1, 1, b'input1')
        buffer.add_input(1, 2, b'input2')
        
        assert 1 in buffer.pending_inputs
        assert len(buffer.pending_inputs[1]) == 2
    
    def test_frame_commit(self):
        """测试帧提交"""
        buffer = FrameBuffer(buffer_size=2)
        
        buffer.add_input(1, 1, b'input1')
        buffer.add_input(1, 2, b'input2')
        
        frame = buffer.try_commit_frame(1, player_count=2)
        
        assert frame is not None
        assert frame.confirmed
        assert 1 in frame.inputs
        assert 2 in frame.inputs
    
    def test_partial_frame_not_committed(self):
        """测试部分输入不提交"""
        buffer = FrameBuffer(buffer_size=2)
        
        buffer.add_input(1, 1, b'input1')
        
        frame = buffer.try_commit_frame(1, player_count=2)
        
        assert frame is None
    
    def test_cleanup(self):
        """测试清理旧帧"""
        buffer = FrameBuffer(buffer_size=2)
        
        buffer.add_input(1, 1, b'input1')
        buffer.try_commit_frame(1, player_count=1)
        
        buffer.cleanup_old_frames(5)
        
        assert 1 not in buffer.frames
    
    def test_invalid_input_rejected(self):
        """测试无效输入被拒绝"""
        buffer = FrameBuffer(buffer_size=2)
        
        # 负帧ID
        buffer.add_input(-1, 1, b'input')
        assert -1 not in buffer.pending_inputs
        
        # 过大输入
        large_input = b'x' * 2000
        buffer.add_input(1, 1, large_input)
        assert 1 not in buffer.pending_inputs


class TestFrameEngine:
    """FrameEngine 测试"""
    
    def test_engine_tick(self):
        """测试引擎 tick"""
        engine = FrameEngine(player_count=2)
        
        engine.add_input(0, 1, b'input1')
        engine.add_input(0, 2, b'input2')
        
        frame = engine.tick()
        
        assert frame is not None
        assert frame.frame_id == 0
        assert engine.get_current_frame_id() == 1
    
    def test_force_tick(self):
        """测试强制 tick"""
        engine = FrameEngine(player_count=2)
        
        engine.add_input(0, 1, b'input1')
        
        frame = engine.force_tick()
        
        assert frame is not None
        assert not frame.confirmed
        assert len(frame.inputs) == 2
    
    def test_get_frame(self):
        """测试获取历史帧"""
        engine = FrameEngine(player_count=2)
        
        engine.add_input(0, 1, b'input1')
        engine.add_input(0, 2, b'input2')
        engine.tick()
        
        frame = engine.get_frame(0)
        assert frame is not None
        assert frame.frame_id == 0
        
        # 不存在的帧
        frame = engine.get_frame(999)
        assert frame is None
    
    def test_frame_history_cleanup(self):
        """测试帧历史自动清理"""
        engine = FrameEngine(player_count=1)
        engine.max_history = 5
        
        for i in range(10):
            engine.add_input(i, 1, b'input')
            engine.tick()
        
        # max_history=5 时，保留的帧数是 max_history + 1 = 6
        # 因为清理逻辑是 oldest = current_frame - max_history
        # 当 current_frame=10, oldest=5，保留 frame_id >= 5 的帧（5,6,7,8,9）
        assert len(engine.frame_history) <= engine.max_history + 1


# ==================== Input 测试 ====================

class TestPlayerInput:
    """PlayerInput 测试"""
    
    def test_input_serialization(self):
        """测试输入序列化"""
        input1 = PlayerInput(
            frame_id=1,
            player_id=2,
            flags=InputFlags.MOVE_RIGHT | InputFlags.ATTACK,
            target_x=100,
            target_y=200
        )
        
        data = input1.serialize()
        input2 = PlayerInput.deserialize(data)
        
        assert input2.frame_id == input1.frame_id
        assert input2.player_id == input1.player_id
        assert input2.flags == input1.flags
        assert input2.target_x == input1.target_x
        assert input2.target_y == input1.target_y
    
    def test_input_flags(self):
        """测试输入标志"""
        input_data = PlayerInput(frame_id=1, player_id=1)
        
        input_data.set_flag(InputFlags.MOVE_RIGHT)
        assert input_data.has_flag(InputFlags.MOVE_RIGHT)
        assert not input_data.has_flag(InputFlags.MOVE_LEFT)
        
        input_data.clear_flag(InputFlags.MOVE_RIGHT)
        assert not input_data.has_flag(InputFlags.MOVE_RIGHT)
    
    def test_input_direction(self):
        """测试输入方向"""
        input_data = PlayerInput(frame_id=1, player_id=1)
        
        input_data.set_flag(InputFlags.MOVE_UP)
        dx, dy = input_data.get_direction()
        assert dy == -1
        
        input_data.set_flag(InputFlags.MOVE_DOWN)
        dx, dy = input_data.get_direction()
        assert dy == 1
    
    def test_invalid_deserialize(self):
        """测试无效数据反序列化"""
        with pytest.raises(ValueError):
            PlayerInput.deserialize(b'short')


class TestInputManager:
    """InputManager 测试"""
    
    def test_input_flow(self):
        """测试输入流程"""
        manager = InputManager(player_id=1)
        
        manager.begin_frame(1)
        manager.set_input(InputFlags.MOVE_RIGHT | InputFlags.ATTACK)
        result = manager.end_frame()
        
        assert result is not None
        assert result.frame_id == 1
        assert result.has_flag(InputFlags.MOVE_RIGHT)
        assert result.has_flag(InputFlags.ATTACK)
    
    def test_history_storage(self):
        """测试历史存储"""
        manager = InputManager(player_id=1)
        
        manager.begin_frame(1)
        manager.set_input(InputFlags.MOVE_RIGHT)
        manager.end_frame()
        
        # 检查 bytes 格式存储
        assert 1 in manager.input_history
        assert isinstance(manager.input_history[1], bytes)
        
        # 检查解析后存储
        assert 1 in manager.parsed_history
        assert manager.parsed_history[1].has_flag(InputFlags.MOVE_RIGHT)


class TestInputValidator:
    """InputValidator 测试"""
    
    def test_valid_input(self):
        """测试有效输入"""
        validator = InputValidator(max_apm=600)
        
        input_data = PlayerInput(frame_id=1, player_id=1)
        
        assert validator.validate(1, input_data)
    
    def test_input_range(self):
        """测试输入范围"""
        validator = InputValidator()

        assert validator.check_input_range(100, 100)
        # MAX_COORD = 10000 << 16 = 655360000，需要更大的数才会失败
        assert not validator.check_input_range(1000000000, 100)  # 1 billion > MAX_COORD
    
    def test_frame_id_validation(self):
        """测试帧ID验证"""
        validator = InputValidator()
        
        assert validator.validate_frame_id(100, 100)
        assert validator.validate_frame_id(150, 100)
        assert not validator.validate_frame_id(-1, 100)
        assert not validator.validate_frame_id(300, 100)  # 超过 MAX_FRAME_AHEAD
    
    def test_bytes_validation(self):
        """测试 bytes 格式验证"""
        validator = InputValidator()
        
        input_data = PlayerInput(frame_id=1, player_id=1, flags=InputFlags.MOVE_RIGHT)
        serialized = input_data.serialize()
        
        assert validator.validate(1, serialized)
        
        # 过大的输入
        large_data = b'x' * 2000
        assert not validator.validate(1, large_data)


# ==================== Physics 测试 ====================

class TestEntity:
    """Entity 测试"""
    
    def test_entity_creation(self):
        """测试实体创建"""
        entity = Entity.from_float(1, 100.0, 200.0)
        
        assert entity.entity_id == 1
        x, y = entity.to_float()
        assert x == 100.0
        assert y == 200.0
    
    def test_entity_position_update(self):
        """测试位置更新"""
        entity = Entity(entity_id=1, x=0, y=0)
        entity.vx = 200 << 16  # 200 像素/秒
        
        entity.update_position(1000)  # 1秒
        
        x, _ = entity.to_int()
        assert x == 200
    
    def test_entity_zero_dt(self):
        """测试零时间增量"""
        entity = Entity(entity_id=1, x=0, y=0)
        entity.vx = 200 << 16
        
        entity.update_position(0)  # dt=0
        
        assert entity.x == 0  # 不应该移动
    
    def test_entity_reset(self):
        """测试实体重置"""
        entity = Entity(entity_id=1, x=100 << 16, y=100 << 16)
        entity.vx = 50 << 16
        
        entity.reset()
        
        assert entity.x == 0
        assert entity.y == 0
        assert entity.vx == 0


class TestPhysicsEngine:
    """PhysicsEngine 测试"""
    
    def test_add_remove_entity(self):
        """测试添加移除实体"""
        engine = PhysicsEngine()
        entity = Entity(entity_id=1)
        
        engine.add_entity(entity)
        assert engine.get_entity(1) is not None
        
        engine.remove_entity(1)
        assert engine.get_entity(1) is None
    
    def test_physics_determinism(self):
        """测试物理确定性"""
        # 两个独立的物理引擎
        engine1 = PhysicsEngine()
        engine2 = PhysicsEngine()
        
        # 相同的初始状态
        entity1 = Entity(entity_id=1, x=100 << 16, y=0)
        entity2 = Entity(entity_id=1, x=100 << 16, y=0)
        
        entity1.vy = 100 << 16
        entity2.vy = 100 << 16
        
        engine1.add_entity(entity1)
        engine2.add_entity(entity2)
        
        # 执行100帧
        for _ in range(100):
            engine1.update(33)
            engine2.update(33)
        
        # 验证状态一致
        e1 = engine1.get_entity(1)
        e2 = engine2.get_entity(1)
        
        assert e1.x == e2.x
        assert e1.y == e2.y
    
    def test_collision_detection(self):
        """测试碰撞检测"""
        engine = PhysicsEngine()
        
        # 两个重叠的实体
        entity1 = Entity(entity_id=1, x=0, y=0)
        entity2 = Entity(entity_id=2, x=16 << 16, y=0)  # 部分重叠
        
        engine.add_entity(entity1)
        engine.add_entity(entity2)
        
        engine.update(33)
        
        assert len(engine.collision_pairs) == 1
    
    def test_zero_dt_update(self):
        """测试零时间增量更新"""
        engine = PhysicsEngine()
        entity = Entity(entity_id=1, x=0, y=0)
        entity.vy = 100 << 16
        
        engine.add_entity(entity)
        engine.update(0)  # dt=0
        
        # 不应该移动
        assert entity.x == 0
        assert entity.y == 0


class TestEntityPool:
    """EntityPool 测试"""
    
    def test_acquire_release(self):
        """测试获取和释放"""
        pool = EntityPool(initial_size=5)
        
        entity = pool.acquire(1)
        assert entity.entity_id == 1
        
        pool.release(entity)
        
        # 再次获取应该从池中取
        entity2 = pool.acquire(2)
        assert entity2.entity_id == 2
    
    def test_pool_exhaustion(self):
        """测试池耗尽"""
        pool = EntityPool(initial_size=2)
        
        pool.acquire(1)
        pool.acquire(2)
        
        # 池空了，应该创建新实体
        entity = pool.acquire(3)
        assert entity is not None


# ==================== RNG 测试 ====================

class TestDeterministicRNG:
    """DeterministicRNG 测试"""
    
    def test_determinism(self):
        """测试确定性"""
        rng1 = DeterministicRNG(12345)
        rng2 = DeterministicRNG(12345)
        
        for _ in range(100):
            assert rng1.range(0, 100) == rng2.range(0, 100)
    
    def test_different_seeds(self):
        """测试不同种子"""
        rng1 = DeterministicRNG(12345)
        rng2 = DeterministicRNG(54321)
        
        values1 = [rng1.range(0, 100) for _ in range(10)]
        values2 = [rng2.range(0, 100) for _ in range(10)]
        
        assert values1 != values2
    
    def test_range(self):
        """测试范围"""
        rng = DeterministicRNG(12345)
        
        for _ in range(1000):
            val = rng.range(10, 20)
            assert 10 <= val <= 20
    
    def test_uniform(self):
        """测试均匀分布"""
        rng = DeterministicRNG(12345)
        
        for _ in range(1000):
            val = rng.uniform()
            assert 0 <= val < 1
    
    def test_zero_seed(self):
        """测试零种子"""
        rng = DeterministicRNG(0)
        
        # 零种子应该被转换为非零
        assert rng.state != 0
        assert rng.range(0, 100) >= 0


# ==================== State 测试 ====================

class TestGameState:
    """GameState 测试"""
    
    def test_snapshot_save_restore(self):
        """测试快照保存和恢复"""
        state = GameState()
        state.frame_id = 100
        
        snapshot = state.save_snapshot()
        
        # 修改状态
        state.frame_id = 200
        
        # 恢复
        success = state.restore_snapshot(100)
        
        assert success
        assert state.frame_id == 100
    
    def test_state_hash(self):
        """测试状态哈希"""
        state = GameState()
        state.frame_id = 100
        
        hash1 = state.compute_state_hash()
        
        state.frame_id = 200
        hash2 = state.compute_state_hash()
        
        assert hash1 != hash2
    
    def test_rollback(self):
        """测试回滚"""
        state = GameState()
        
        # 创建多个快照
        state.frame_id = 10
        state.save_snapshot()
        
        state.frame_id = 20
        state.save_snapshot()
        
        state.frame_id = 30
        
        # 回滚到20
        assert state.rollback_to(20)
        assert state.frame_id == 20
        
        # 回滚到不存在的快照
        assert not state.rollback_to(999)


class TestStateValidator:
    """StateValidator 测试"""
    
    def test_hash_verification(self):
        """测试哈希验证"""
        validator = StateValidator()
        
        validator.record_hash(1, "abc123")
        
        assert validator.verify_hash(1, "abc123")
        assert not validator.verify_hash(1, "xyz789")
    
    def test_mismatch_tracking(self):
        """测试不匹配追踪"""
        validator = StateValidator()
        
        validator.record_hash(1, "abc")
        validator.verify_hash(1, "xyz")
        
        mismatches = validator.get_mismatches()
        assert len(mismatches) == 1
        assert mismatches[0]['frame_id'] == 1


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
