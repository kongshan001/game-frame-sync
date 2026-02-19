"""
游戏全局配置模块

集中管理所有游戏配置，避免霰弹式修改。
只需修改这里的值即可全局生效。

使用方法：
    from core.config import CONFIG
    
    # 读取配置
    gravity = CONFIG.GRAVITY
    fps = CONFIG.FRAME_RATE
    
    # 修改配置（测试时）
    CONFIG.GRAVITY = 500.0
"""

from dataclasses import dataclass, field
from typing import Optional
import json
from pathlib import Path

from .fixed import fixed, FixedPoint


@dataclass
class PhysicsConfig:
    """
    物理引擎配置
    
    所有物理相关的常量都在这里定义。
    """
    
    # 重力加速度（像素/秒²）
    GRAVITY: float = 980.0
    
    # 摩擦系数 (0-1)
    FRICTION: float = 0.9
    
    # 最大速度（像素/秒）
    MAX_VELOCITY: float = 1000.0
    
    # 世界边界
    WORLD_WIDTH: float = 1920.0
    WORLD_HEIGHT: float = 1080.0
    
    # 实体默认大小
    ENTITY_WIDTH: float = 32.0
    ENTITY_HEIGHT: float = 32.0
    
    # 空间网格单元大小
    GRID_CELL_SIZE: float = 64.0
    
    @property
    def GRAVITY_FIXED(self) -> FixedPoint:
        """重力（定点数）"""
        return fixed(self.GRAVITY)
    
    @property
    def FRICTION_FIXED(self) -> FixedPoint:
        """摩擦系数（定点数）"""
        return fixed(self.FRICTION)
    
    @property
    def MAX_VELOCITY_FIXED(self) -> FixedPoint:
        """最大速度（定点数）"""
        return fixed(self.MAX_VELOCITY)


@dataclass
class NetworkConfig:
    """
    网络配置
    """
    
    # 帧率
    FRAME_RATE: int = 30
    
    # 帧缓冲大小
    BUFFER_SIZE: int = 3
    
    # 服务器端口
    SERVER_PORT: int = 8765
    
    # 超时设置
    AUTH_TIMEOUT: float = 5.0
    PING_INTERVAL: float = 20.0
    PING_TIMEOUT: float = 10.0
    
    # 速率限制
    MAX_REQUESTS_PER_SECOND: int = 100
    
    # 最大超前帧数
    MAX_FRAME_AHEAD: int = 100
    
    @property
    def FRAME_TIME_MS(self) -> int:
        """每帧时间（毫秒）"""
        return 1000 // self.FRAME_RATE
    
    @property
    def FRAME_TIME_SEC(self) -> float:
        """每帧时间（秒）"""
        return 1.0 / self.FRAME_RATE


@dataclass
class GameConfig:
    """
    游戏逻辑配置
    """
    
    # 玩家数量
    PLAYER_COUNT: int = 2
    MAX_PLAYERS_PER_ROOM: int = 4
    
    # 玩家速度
    PLAYER_SPEED: float = 300.0
    
    # 攻击参数
    ATTACK_RANGE: float = 60.0
    ATTACK_DAMAGE: int = 10
    
    # 默认 HP
    DEFAULT_HP: int = 100
    
    @property
    def PLAYER_SPEED_FIXED(self) -> FixedPoint:
        """玩家速度（定点数）"""
        return fixed(self.PLAYER_SPEED)


@dataclass
class HistoryConfig:
    """
    历史记录配置
    """
    
    # 帧历史最大数量
    MAX_FRAME_HISTORY: int = 300  # 10秒 @ 30fps
    
    # 快照最大数量
    MAX_SNAPSHOTS: int = 60  # 2秒 @ 30fps


@dataclass
class Config:
    """
    全局配置类
    
    所有配置的根节点。修改这里的属性会全局生效。
    
    使用方法:
        from core.config import CONFIG
        
        # 读取
        print(CONFIG.physics.GRAVITY)
        print(CONFIG.network.FRAME_RATE)
        
        # 修改（运行时）
        CONFIG.physics.GRAVITY = 500.0
    
    从文件加载:
        CONFIG.load_from_file('config.json')
    """
    
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    game: GameConfig = field(default_factory=GameConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    
    def load_from_file(self, path: str) -> bool:
        """
        从 JSON 文件加载配置
        
        Args:
            path: 配置文件路径
        
        Returns:
            True 如果成功
        """
        try:
            config_path = Path(path)
            if not config_path.exists():
                return False
            
            with open(config_path, 'r') as f:
                data = json.load(f)
            
            # 更新各部分配置
            if 'physics' in data:
                for key, value in data['physics'].items():
                    if hasattr(self.physics, key):
                        setattr(self.physics, key, value)
            
            if 'network' in data:
                for key, value in data['network'].items():
                    if hasattr(self.network, key):
                        setattr(self.network, key, value)
            
            if 'game' in data:
                for key, value in data['game'].items():
                    if hasattr(self.game, key):
                        setattr(self.game, key, value)
            
            return True
            
        except Exception as e:
            print(f"Failed to load config: {e}")
            return False
    
    def save_to_file(self, path: str) -> bool:
        """
        保存配置到 JSON 文件
        
        Args:
            path: 配置文件路径
        
        Returns:
            True 如果成功
        """
        try:
            from dataclasses import asdict
            
            data = {
                'physics': asdict(self.physics),
                'network': asdict(self.network),
                'game': asdict(self.game),
                'history': asdict(self.history),
            }
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
            
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False
    
    def to_dict(self) -> dict:
        """转换为字典"""
        from dataclasses import asdict
        return {
            'physics': asdict(self.physics),
            'network': asdict(self.network),
            'game': asdict(self.game),
            'history': asdict(self.history),
        }


# ============ 全局配置实例 ============
# 所有模块应该使用这个实例，而不是创建新的

CONFIG = Config()


# ============ 便捷访问 ============

def get_config() -> Config:
    """获取全局配置"""
    return CONFIG


def reset_config():
    """重置配置为默认值"""
    global CONFIG
    CONFIG = Config()
