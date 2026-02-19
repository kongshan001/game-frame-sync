"""
Simple 2D demo game for frame synchronization visualization

重构说明：
- 使用 core.config.CONFIG 替代本地 GameConfig
- 使用 core.fixed.fixed() 创建定点数
- 移除所有硬编码的 << 16
"""

import asyncio
import pygame
import sys
import time
import math
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

# 添加父目录到路径
sys.path.insert(0, str(__file__).rsplit('/demo', 1)[0])

from core.frame import FrameEngine, Frame
from core.input import InputFlags, PlayerInput
from core.physics import PhysicsEngine, Entity
from core.state import GameState
from core.rng import DeterministicRNG
from core.fixed import fixed, FixedPoint
from core.config import CONFIG


# ==================== 颜色定义 ====================

COLORS = {
    'background': (30, 30, 40),
    'grid': (50, 50, 60),
    'player1': (100, 200, 255),
    'player2': (255, 150, 100),
    'player3': (100, 255, 150),
    'player4': (255, 255, 100),
    'text': (255, 255, 255),
    'prediction': (255, 100, 100, 128),
    'confirmed': (100, 255, 100),
    'attack': (255, 50, 50),
}

PLAYER_COLORS = [COLORS['player1'], COLORS['player2'], COLORS['player3'], COLORS['player4']]


# ==================== 演示专用配置 ====================

@dataclass
class DemoConfig:
    """演示专用配置（覆盖全局配置）"""
    width: int = 1200
    height: int = 700
    fps: int = 60
    logic_fps: int = 30
    player_count: int = 2
    buffer_size: int = 3
    player_speed: int = 300
    attack_range: int = 60
    attack_damage: int = 10


# ==================== 本地游戏模拟器 ====================

class LocalGameSimulator:
    """
    本地游戏模拟器（单机模拟帧同步）
    用于演示和理解帧同步原理
    """
    
    def __init__(self, config: DemoConfig):
        self.config = config
        
        # 更新全局配置
        CONFIG.physics.WORLD_WIDTH = float(config.width)
        CONFIG.physics.WORLD_HEIGHT = float(config.height)
        CONFIG.game.PLAYER_SPEED = float(config.player_speed)
        CONFIG.game.ATTACK_RANGE = float(config.attack_range)
        CONFIG.game.ATTACK_DAMAGE = config.attack_damage
        
        # 游戏状态
        self.game_state = GameState()
        self.physics = PhysicsEngine()  # 使用更新后的 CONFIG
        
        # 帧引擎
        self.frame_engine = FrameEngine(
            player_count=config.player_count,
            buffer_size=config.buffer_size
        )
        
        # 玩家输入
        self.pending_inputs: Dict[int, Dict[int, bytes]] = {}
        self.player_inputs: Dict[int, int] = {}
        
        # 统计
        self.current_frame = 0
        self.frame_history: List[Frame] = []
        self._last_attacks: List[dict] = []
        
        # 初始化玩家
        self._init_players()
    
    def _init_players(self):
        """初始化玩家实体"""
        spawn_positions = [
            (200, 350),
            (1000, 350),
            (200, 550),
            (1000, 550),
        ]
        
        for i in range(self.config.player_count):
            x, y = spawn_positions[i]
            entity = Entity.from_float(i, float(x), float(y))
            self.physics.add_entity(entity)
            self.game_state.add_entity(entity)
            self.game_state.bind_player_entity(i, i)
            self.player_inputs[i] = 0
    
    def set_player_input(self, player_id: int, flags: int):
        """设置玩家输入"""
        self.player_inputs[player_id] = flags
    
    def tick(self) -> Optional[Frame]:
        """执行一帧"""
        for player_id in range(self.config.player_count):
            flags = self.player_inputs.get(player_id, 0)
            
            input_data = PlayerInput(
                frame_id=self.current_frame,
                player_id=player_id,
                flags=flags
            ).serialize()
            
            self.frame_engine.add_input(self.current_frame, player_id, input_data)
        
        frame = self.frame_engine.tick()
        
        if frame:
            self._apply_frame(frame)
            self.frame_history.append(frame)
            self.current_frame += 1
        
        return frame
    
    def _apply_frame(self, frame: Frame):
        """应用帧输入到游戏"""
        self._last_attacks = []
        
        for player_id, input_data in frame.inputs.items():
            if not input_data:
                continue
            
            try:
                parsed = PlayerInput.deserialize(input_data)
                entity = self.game_state.get_entity(player_id)
                if entity:
                    self.physics.apply_input(entity.entity_id, parsed.flags)
                    
                    if parsed.flags & InputFlags.ATTACK:
                        attack_info = self._handle_attack(player_id)
                        if attack_info:
                            self._last_attacks.append(attack_info)
            except Exception:
                pass
        
        self.physics.update(33)
    
    def _handle_attack(self, attacker_id: int):
        """处理攻击逻辑"""
        attacker = self.game_state.get_entity(attacker_id)
        if not attacker:
            return None
        
        ax, ay = attacker.to_float()
        hits = []
        
        for target_id in range(self.config.player_count):
            if target_id == attacker_id:
                continue
            
            target = self.game_state.get_entity(target_id)
            if not target or target.hp <= 0:
                continue
            
            tx, ty = target.to_float()
            dist = math.sqrt((ax - tx) ** 2 + (ay - ty) ** 2)
            
            if dist <= self.config.attack_range:
                target.hp = max(0, target.hp - self.config.attack_damage)
                hits.append(target_id)
        
        return {'attacker_id': attacker_id, 'x': ax, 'y': ay, 'hits': hits}
    
    def get_last_attacks(self) -> List[dict]:
        """获取最近一帧的攻击事件"""
        return self._last_attacks
    
    def get_player_position(self, player_id: int) -> Tuple[float, float]:
        """获取玩家位置"""
        entity = self.game_state.get_entity(player_id)
        if entity:
            return entity.to_float()
        return (0.0, 0.0)
    
    def get_player_hp(self, player_id: int) -> int:
        """获取玩家HP"""
        entity = self.game_state.get_entity(player_id)
        if entity:
            return entity.hp
        return 0


# ==================== PyGame 渲染器 ====================

class GameRenderer:
    """PyGame 渲染器"""
    
    def __init__(self, config: DemoConfig):
        self.config = config
        
        pygame.init()
        pygame.display.set_caption("Frame Sync Demo")
        
        self.screen = pygame.display.set_mode((config.width, config.height))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.large_font = pygame.font.Font(None, 36)
        
        self.show_grid = True
        self.show_debug = True
        self.show_help = True
        self.attack_effects: List[dict] = []
    
    def render(self, simulator: LocalGameSimulator, extra_info: dict = None):
        """渲染游戏画面"""
        self.screen.fill(COLORS['background'])
        
        if self.show_grid:
            self._draw_grid()
        
        self._draw_attack_effects()
        
        for player_id in range(simulator.config.player_count):
            self._draw_player(simulator, player_id)
        
        if self.show_debug:
            self._draw_debug_info(simulator, extra_info)
        
        if self.show_help:
            self._draw_help()
        
        pygame.display.flip()
    
    def _draw_grid(self):
        """绘制背景网格"""
        for x in range(0, self.config.width, 50):
            pygame.draw.line(self.screen, COLORS['grid'], (x, 0), (x, self.config.height))
        for y in range(0, self.config.height, 50):
            pygame.draw.line(self.screen, COLORS['grid'], (0, y), (self.config.width, y))
    
    def _draw_attack_effects(self):
        """绘制攻击效果"""
        current_time = time.time() * 1000
        self.attack_effects = [e for e in self.attack_effects 
                               if current_time - e['time'] < 200]
        
        for effect in self.attack_effects:
            age = current_time - effect['time']
            alpha = max(0, 255 - int(age * 1.275))
            
            radius = int(self.config.attack_range * (1 + age / 200))
            color = PLAYER_COLORS[effect['player_id'] % len(PLAYER_COLORS)]
            
            surface = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(surface, (*color, alpha // 2), (radius, radius), radius, 3)
            self.screen.blit(surface, (int(effect['x'] - radius), int(effect['y'] - radius)))
    
    def add_attack_effect(self, x: float, y: float, player_id: int):
        """添加攻击效果"""
        self.attack_effects.append({
            'x': x, 'y': y,
            'time': time.time() * 1000,
            'player_id': player_id
        })
    
    def _draw_player(self, simulator: LocalGameSimulator, player_id: int):
        """绘制玩家"""
        x, y = simulator.get_player_position(player_id)
        hp = simulator.get_player_hp(player_id)
        color = PLAYER_COLORS[player_id % len(PLAYER_COLORS)]
        
        size = 40
        rect = pygame.Rect(int(x - size/2), int(y - size/2), size, size)
        pygame.draw.rect(self.screen, color, rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=8)
        
        text = self.font.render(f"P{player_id + 1}", True, (0, 0, 0))
        self.screen.blit(text, (int(x - 10), int(y - 8)))
        
        hp_bar_width = 50
        hp_bar_height = 6
        hp_x = int(x - hp_bar_width/2)
        hp_y = int(y - size/2 - 15)
        
        pygame.draw.rect(self.screen, (60, 60, 60), 
                        (hp_x, hp_y, hp_bar_width, hp_bar_height))
        hp_width = int(hp_bar_width * hp / 100)
        hp_color = (100, 255, 100) if hp > 50 else (255, 150, 100) if hp > 25 else (255, 100, 100)
        pygame.draw.rect(self.screen, hp_color, 
                        (hp_x, hp_y, hp_width, hp_bar_height))
    
    def _draw_debug_info(self, simulator: LocalGameSimulator, extra_info: dict):
        """绘制调试信息"""
        info = [
            f"Frame: {simulator.current_frame}",
            f"FPS: {int(self.clock.get_fps())}",
            f"Logic FPS: {simulator.config.logic_fps}",
            f"Buffer: {simulator.config.buffer_size}",
        ]
        
        if extra_info:
            info.extend([f"{k}: {v}" for k, v in extra_info.items()])
        
        y = 10
        for line in info:
            text = self.font.render(line, True, COLORS['text'])
            self.screen.blit(text, (10, y))
            y += 22
    
    def _draw_help(self):
        """绘制帮助信息"""
        help_lines = [
            "P1: WASD move, SPACE attack",
            "P2: Arrow keys move, ENTER attack",
            "G: Toggle grid | D: Toggle debug | H: Toggle help",
        ]
        
        y = self.config.height - 70
        for line in help_lines:
            text = self.font.render(line, True, (180, 180, 180))
            self.screen.blit(text, (10, y))
            y += 22
    
    def tick(self):
        """时钟tick"""
        return self.clock.tick(self.config.fps)


# ==================== 输入处理 ====================

class InputHandler:
    """输入处理器"""
    
    P1_KEYS = {
        pygame.K_w: InputFlags.MOVE_UP,
        pygame.K_s: InputFlags.MOVE_DOWN,
        pygame.K_a: InputFlags.MOVE_LEFT,
        pygame.K_d: InputFlags.MOVE_RIGHT,
        pygame.K_SPACE: InputFlags.ATTACK,
    }
    
    P2_KEYS = {
        pygame.K_UP: InputFlags.MOVE_UP,
        pygame.K_DOWN: InputFlags.MOVE_DOWN,
        pygame.K_LEFT: InputFlags.MOVE_LEFT,
        pygame.K_RIGHT: InputFlags.MOVE_RIGHT,
        pygame.K_RETURN: InputFlags.ATTACK,
    }
    
    @classmethod
    def get_player_input(cls, player_id: int) -> int:
        """获取玩家输入标志"""
        keys = pygame.key.get_pressed()
        
        key_map = cls.P1_KEYS if player_id == 0 else cls.P2_KEYS
        flags = 0
        
        for key, flag in key_map.items():
            if keys[key]:
                flags |= flag
        
        return flags


# ==================== 主游戏类 ====================

class DemoGame:
    """演示游戏"""
    
    def __init__(self):
        self.config = DemoConfig()
        self.simulator = LocalGameSimulator(self.config)
        self.renderer = GameRenderer(self.config)
        
        self.running = True
        self.paused = False
        
        self.logic_accumulator = 0.0
        self.logic_frame_time = 1000 / self.config.logic_fps
        self.last_time = time.time() * 1000
    
    def handle_events(self):
        """处理事件"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_p:
                    self.paused = not self.paused
                elif event.key == pygame.K_g:
                    self.renderer.show_grid = not self.renderer.show_grid
                elif event.key == pygame.K_d:
                    self.renderer.show_debug = not self.renderer.show_debug
                elif event.key == pygame.K_h:
                    self.renderer.show_help = not self.renderer.show_help
    
    def update(self):
        """更新游戏状态"""
        if self.paused:
            return
        
        current_time = time.time() * 1000
        delta_time = current_time - self.last_time
        self.last_time = current_time
        
        delta_time = min(delta_time, 100)
        
        self.logic_accumulator += delta_time
        
        while self.logic_accumulator >= self.logic_frame_time:
            for player_id in range(self.config.player_count):
                flags = InputHandler.get_player_input(player_id)
                self.simulator.set_player_input(player_id, flags)
            
            self.simulator.tick()
            
            self.logic_accumulator -= self.logic_frame_time
    
    def render(self):
        """渲染画面"""
        extra_info = {'Status': 'PAUSED' if self.paused else 'RUNNING'}
        
        for attack in self.simulator.get_last_attacks():
            self.renderer.add_attack_effect(
                attack['x'], attack['y'], attack['attacker_id']
            )
        
        self.renderer.render(self.simulator, extra_info)
    
    def run(self):
        """主循环"""
        print("=" * 50)
        print("Frame Sync Demo")
        print("=" * 50)
        print("\nControls:")
        print("  Player 1: WASD to move, SPACE to attack")
        print("  Player 2: Arrow keys to move, ENTER to attack")
        print("\nPress P to pause, ESC to quit")
        print("=" * 50)
        
        while self.running:
            self.handle_events()
            self.update()
            self.render()
            
            self.renderer.tick()
        
        pygame.quit()
        print("\nGame ended.")


# ==================== 入口 ====================

def main():
    """主函数"""
    game = DemoGame()
    game.run()


if __name__ == '__main__':
    main()
