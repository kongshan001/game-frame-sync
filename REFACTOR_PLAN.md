# 代码重构分析报告

## 问题：霰弹式修改 (Shotgun Surgery)

### 当前问题

当需要修改定点数格式（如从 16.16 改为 24.8）时，需要在多个地方修改：

| 文件 | 问题点 |
|------|--------|
| `core/physics.py` | Entity.FIXED_SHIFT, FIXED_SCALE, 硬编码 `<< 16` |
| `demo/simple_game.py` | 硬编码 `<< 16`, 物理常量 |
| `tests/` | 大量硬编码 `<< 16` |
| `server/main.py` | MAX_FRAME_AHEAD 等常量 |

### 根本原因

1. **缺乏抽象层**: 定点数操作散落在各处
2. **魔法数字**: 直接使用 `16`, `65536`, `<< 16`
3. **常量分散**: FIXED_SHIFT 只在 Entity 类中定义
4. **紧耦合**: 物理引擎直接使用 Entity 的类常量

---

## 重构方案

### 方案1：创建 FixedPoint 工具类（推荐）

```python
# core/fixed.py
@dataclass
class FixedPoint:
    """统一的定点数抽象"""
    
    # 单一配置点 - 只需修改这里
    FRACTION_BITS: ClassVar[int] = 16
    SCALE: ClassVar[int] = 1 << FRACTION_BITS
    MAX_VALUE: ClassVar[int] = (1 << 31) - 1
    
    raw: int = 0
    
    @classmethod
    def from_float(cls, value: float) -> 'FixedPoint':
        return cls(raw=int(value * cls.SCALE))
    
    def to_float(self) -> float:
        return self.raw / self.SCALE
    
    def __add__(self, other: 'FixedPoint') -> 'FixedPoint':
        return FixedPoint(self.raw + other.raw)
    
    def __mul__(self, other: 'FixedPoint') -> 'FixedPoint':
        return FixedPoint((self.raw * other.raw) >> self.FRACTION_BITS)
    
    # ... 其他运算

# 便捷函数
def fixed(x: float) -> FixedPoint:
    return FixedPoint.from_float(x)
```

### 方案2：配置文件集中管理

```python
# core/config.py
@dataclass
class GameConfig:
    """游戏全局配置"""
    
    # 定点数配置
    FIXED_FRACTION_BITS: int = 16
    FIXED_SCALE: int = 1 << 16
    
    # 物理常量
    GRAVITY: float = 980.0  # 自动转换为定点数
    FRICTION: float = 0.9
    MAX_VELOCITY: float = 1000.0
    
    # 世界大小
    WORLD_WIDTH: float = 1920.0
    WORLD_HEIGHT: float = 1080.0
    
    # 网络配置
    FRAME_RATE: int = 30
    BUFFER_SIZE: int = 3

# 全局实例
CONFIG = GameConfig()
```

### 方案3：使用依赖注入

```python
class PhysicsEngine:
    def __init__(self, config: GameConfig):
        self.config = config
        
        # 使用配置，不硬编码
        self.GRAVITY = int(config.GRAVITY * config.FIXED_SCALE)
        self.FRICTION = int(config.FRICTION * config.FIXED_SCALE)
```

---

## 需要重构的模块

| 优先级 | 模块 | 修改内容 |
|--------|------|----------|
| P0 | 新建 `core/fixed.py` | 定点数抽象类 |
| P0 | 新建 `core/config.py` | 全局配置类 |
| P1 | `core/physics.py` | 使用 FixedPoint, 注入 config |
| P1 | `core/entity.py` (拆分) | Entity 从 physics 分离 |
| P2 | `demo/simple_game.py` | 使用 config |
| P2 | `tests/` | 使用 FixedPoint 工厂方法 |
| P3 | `server/main.py` | 使用 config |

---

## 重构后的好处

1. **单一修改点**: 只需改 `GameConfig` 或 `FixedPoint.FRACTION_BITS`
2. **类型安全**: FixedPoint 类型明确，IDE 自动补全
3. **可测试性**: 可以注入不同的配置测试
4. **可读性**: `fixed(100.5)` 比 `100 << 16` 更清晰

---

## 建议的重构顺序

1. 创建 `core/fixed.py` - 定点数抽象
2. 创建 `core/config.py` - 全局配置
3. 重构 `core/physics.py` - 使用新抽象
4. 添加测试 - 确保重构不破坏功能
5. 逐步迁移其他模块
