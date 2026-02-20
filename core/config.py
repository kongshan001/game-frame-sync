"""
游戏全局配置模块

支持从 JSON 配置文件加载配置，方便非程序员修改。

使用方法：
    from core.config import CONFIG
    
    # 自动加载 config.json
    print(CONFIG.physics.GRAVITY)
    
    # 或指定配置文件
    CONFIG.load_from_file('custom_config.json')

配置文件格式：
    config.json - 见项目根目录的 config.json 示例
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, ClassVar
import json
from pathlib import Path


@dataclass
class FixedPointConfig:
    """
    定点数配置
    
    属性:
        fraction_bits: 小数位数（默认16，即16.16格式）
    """
    fraction_bits: int = 16
    
    @property
    def scale(self) -> int:
        """缩放因子"""
        return 1 << self.fraction_bits


@dataclass
class PhysicsConfig:
    """
    物理引擎配置
    
    所有物理相关的常量都在这里定义。
    单位：像素、像素/秒、像素/秒²
    """
    
    gravity: float = 980.0
    friction: float = 0.9
    max_velocity: float = 1000.0
    world_width: float = 1920.0
    world_height: float = 1080.0
    entity_width: float = 32.0
    entity_height: float = 32.0
    grid_cell_size: float = 64.0
    
    def get_gravity_fixed(self, scale: int) -> int:
        """重力（定点数）"""
        return int(self.gravity * scale)
    
    def get_friction_fixed(self, scale: int) -> int:
        """摩擦系数（定点数）"""
        return int(self.friction * scale)
    
    def get_max_velocity_fixed(self, scale: int) -> int:
        """最大速度（定点数）"""
        return int(self.max_velocity * scale)


@dataclass
class NetworkConfig:
    """
    网络配置
    """
    
    frame_rate: int = 30
    buffer_size: int = 3
    server_port: int = 8765
    auth_timeout: float = 5.0
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    max_requests_per_second: int = 100
    max_frame_ahead: int = 100
    
    @property
    def frame_time_ms(self) -> int:
        """每帧时间（毫秒）"""
        return 1000 // self.frame_rate
    
    @property
    def frame_time_sec(self) -> float:
        """每帧时间（秒）"""
        return 1.0 / self.frame_rate


@dataclass
class GameConfig:
    """
    游戏逻辑配置
    """
    
    player_count: int = 2
    max_players_per_room: int = 4
    player_speed: float = 300.0
    attack_range: float = 60.0
    attack_damage: int = 10
    default_hp: int = 100
    
    def get_player_speed_fixed(self, scale: int) -> int:
        """玩家速度（定点数）"""
        return int(self.player_speed * scale)


@dataclass
class HistoryConfig:
    """
    历史记录配置
    """
    
    max_frame_history: int = 300  # 10秒 @ 30fps
    max_snapshots: int = 60  # 2秒 @ 30fps


@dataclass
class Config:
    """
    全局配置类
    
    从 JSON 文件加载配置，支持热重载。
    
    使用方法:
        from core.config import CONFIG
        
        print(CONFIG.physics.gravity)
        print(CONFIG.network.frame_rate)
    
    从文件加载:
        CONFIG.load_from_file('config.json')
    
    保存到文件:
        CONFIG.save_to_file('config.json')
    """
    
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    game: GameConfig = field(default_factory=GameConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    fixed_point: FixedPointConfig = field(default_factory=FixedPointConfig)
    
    # 配置文件路径
    _config_path: Optional[str] = field(default=None, repr=False)
    _loaded: bool = field(default=False, repr=False)
    
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
                print(f"[Config] 配置文件不存在: {path}")
                return False
            
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 更新各部分配置
            if 'physics' in data:
                self._update_dataclass(self.physics, data['physics'])
            
            if 'network' in data:
                self._update_dataclass(self.network, data['network'])
            
            if 'game' in data:
                self._update_dataclass(self.game, data['game'])
            
            if 'history' in data:
                self._update_dataclass(self.history, data['history'])
            
            if 'fixed_point' in data:
                self._update_dataclass(self.fixed_point, data['fixed_point'])
            
            self._config_path = path
            self._loaded = True
            print(f"[Config] 已加载配置: {path}")
            return True
            
        except json.JSONDecodeError as e:
            print(f"[Config] JSON 解析错误: {e}")
            return False
        except Exception as e:
            print(f"[Config] 加载配置失败: {e}")
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
            data = {
                'physics': asdict(self.physics),
                'network': asdict(self.network),
                'game': asdict(self.game),
                'history': asdict(self.history),
                'fixed_point': asdict(self.fixed_point),
            }
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"[Config] 已保存配置: {path}")
            return True
            
        except Exception as e:
            print(f"[Config] 保存配置失败: {e}")
            return False
    
    def reload(self) -> bool:
        """
        重新加载配置文件
        
        Returns:
            True 如果成功
        """
        if self._config_path:
            return self.load_from_file(self._config_path)
        return False
    
    @staticmethod
    def _update_dataclass(obj, data: dict):
        """更新 dataclass 对象的属性"""
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'physics': asdict(self.physics),
            'network': asdict(self.network),
            'game': asdict(self.game),
            'history': asdict(self.history),
            'fixed_point': asdict(self.fixed_point),
        }
    
    def __str__(self) -> str:
        """友好的字符串表示"""
        lines = ["=== 游戏配置 ==="]
        lines.append(f"物理: 重力={self.physics.gravity}, 摩擦={self.physics.friction}")
        lines.append(f"网络: 帧率={self.network.frame_rate}fps, 缓冲={self.network.buffer_size}")
        lines.append(f"游戏: 玩家速度={self.game.player_speed}, 攻击范围={self.game.attack_range}")
        lines.append(f"定点数: {self.fixed_point.fraction_bits}.{self.fixed_point.fraction_bits}格式")
        return '\n'.join(lines)


# ============ 全局配置实例 ============

CONFIG = Config()

# 配置文件路径（用于延迟加载）
_config_loaded = False
_default_config_paths = [
    Path(__file__).parent.parent / 'config.json',  # 项目根目录
    Path.cwd() / 'config.json',  # 当前工作目录
]


def _ensure_config_loaded():
    """确保配置已加载（延迟加载，避免循环导入）"""
    global _config_loaded, CONFIG
    
    if _config_loaded:
        return
    
    for config_path in _default_config_paths:
        if config_path.exists():
            CONFIG.load_from_file(str(config_path))
            break
    
    # 配置定点数精度（延迟导入避免循环依赖）
    try:
        from .fixed import FixedPoint
        FixedPoint.configure(CONFIG.fixed_point.fraction_bits)
    except ImportError:
        pass
    
    _config_loaded = True


# 模块加载时不自动初始化，等第一次使用时再初始化
# 这样可以避免循环导入问题


# ============ 便捷访问 ============

def get_config() -> Config:
    """获取全局配置"""
    return CONFIG


def load_config(path: str) -> Config:
    """
    加载指定配置文件
    
    Args:
        path: 配置文件路径
    
    Returns:
        Config 实例
    """
    CONFIG.load_from_file(path)
    return CONFIG


def reset_config():
    """重置配置为默认值"""
    global CONFIG
    CONFIG = Config()
