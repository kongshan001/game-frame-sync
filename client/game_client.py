"""
Frame synchronization game client
"""

import asyncio
import time
import logging
from typing import Optional, Callable, Dict
import msgpack
import websockets

from core.frame import Frame
from core.input import InputManager, PlayerInput
from core.state import GameState

logger = logging.getLogger(__name__)


class GameClient:
    """
    帧同步游戏客户端
    负责与服务器的通信、输入管理、帧同步
    """
    
    FRAME_RATE = 30
    
    def __init__(self, config: dict = None):
        """
        初始化客户端
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 连接信息
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.player_id: Optional[str] = None
        self.room_id: Optional[str] = None
        self.connected = False
        
        # 游戏状态
        self.game_state = GameState()
        self.input_manager: Optional[InputManager] = None
        
        # 帧缓冲
        self.frame_buffer: Dict[int, Frame] = {}
        self.current_frame = 0
        self.last_confirmed_frame = -1
        
        # 回调
        self.on_frame_callback: Optional[Callable] = None
        self.on_state_callback: Optional[Callable] = None
        
        # 任务
        self.recv_task: Optional[asyncio.Task] = None
        self.running = False
    
    async def connect(self, server_url: str, player_id: str, room_id: str) -> bool:
        """
        连接到服务器
        
        Args:
            server_url: 服务器地址 (ws://host:port)
            player_id: 玩家ID
            room_id: 房间ID
        
        Returns:
            是否连接成功
        """
        try:
            self.player_id = player_id
            self.room_id = room_id
            
            # 建立 WebSocket 连接
            self.websocket = await asyncio.wait_for(
                websockets.connect(server_url),
                timeout=10.0
            )
            
            # 发送认证消息
            await self.websocket.send(msgpack.packb({
                'player_id': player_id,
                'room_id': room_id
            }))
            
            # 等待加入成功
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            
            data = msgpack.unpackb(response, raw=False)
            if data.get('type') == 'join_success':
                self.connected = True
                self.running = True
                
                # 初始化输入管理器
                player_num = int(player_id.split('_')[-1]) if '_' in player_id else 0
                self.input_manager = InputManager(player_num)
                
                # 启动接收任务
                self.recv_task = asyncio.create_task(self._recv_loop())
                
                logger.info(f"Connected to room {room_id} as {player_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """断开连接"""
        self.running = False
        self.connected = False
        
        if self.recv_task:
            self.recv_task.cancel()
            try:
                await self.recv_task
            except asyncio.CancelledError:
                pass
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
    
    async def _recv_loop(self):
        """接收消息循环"""
        try:
            async for message in self.websocket:
                await self._handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed by server")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self.connected = False
    
    async def _handle_message(self, message: bytes):
        """处理服务器消息"""
        try:
            data = msgpack.unpackb(message, raw=False)
            msg_type = data.get('type')
            payload = data.get('payload', {})
            
            if msg_type == 'game_frame':
                await self._handle_game_frame(payload)
            elif msg_type == 'player_joined':
                logger.info(f"Player joined: {payload.get('player_id')}")
            elif msg_type == 'player_left':
                logger.info(f"Player left: {payload.get('player_id')}")
            elif msg_type == 'game_start':
                logger.info(f"Game starting at frame {payload.get('start_frame')}")
            
        except Exception as e:
            logger.error(f"Message handling error: {e}")
    
    async def _handle_game_frame(self, payload: dict):
        """处理游戏帧"""
        frame_id = payload.get('frame_id')
        inputs = payload.get('inputs', {})
        confirmed = payload.get('confirmed', False)
        
        # 转换输入格式
        input_data = {int(k): v for k, v in inputs.items()}
        
        # 存储帧
        frame = Frame(
            frame_id=frame_id,
            inputs=input_data,
            confirmed=confirmed
        )
        
        self.frame_buffer[frame_id] = frame
        
        if confirmed:
            self.last_confirmed_frame = frame_id
        
        # 触发回调
        if self.on_frame_callback:
            await self.on_frame_callback(frame)
    
    def set_input(self, flags: int, target_x: int = 0, target_y: int = 0):
        """
        设置当前帧输入
        
        Args:
            flags: 输入标志
            target_x: 目标X
            target_y: 目标Y
        """
        if self.input_manager:
            self.input_manager.begin_frame(self.current_frame)
            self.input_manager.set_input(flags, target_x, target_y)
    
    async def send_input(self) -> bool:
        """
        发送当前输入到服务器
        
        Returns:
            是否发送成功
        """
        if not self.connected or not self.input_manager:
            return False
        
        input_data = self.input_manager.end_frame()
        if not input_data:
            return False
        
        try:
            await self.websocket.send(msgpack.packb({
                'type': 'input',
                'payload': {
                    'frame_id': self.current_frame,
                    'input_data': input_data.serialize()
                }
            }))
            
            self.current_frame += 1
            return True
            
        except Exception as e:
            logger.error(f"Send input error: {e}")
            return False
    
    def get_frame(self, frame_id: int) -> Optional[Frame]:
        """获取指定帧"""
        return self.frame_buffer.get(frame_id)
    
    def get_next_executable_frame(self) -> Optional[Frame]:
        """获取下一个可执行的帧"""
        if self.last_confirmed_frame >= 0 and self.last_confirmed_frame in self.frame_buffer:
            return self.frame_buffer.pop(self.last_confirmed_frame)
        return None
    
    def on_frame(self, callback: Callable):
        """设置帧回调"""
        self.on_frame_callback = callback
    
    def on_state_update(self, callback: Callable):
        """设置状态更新回调"""
        self.on_state_callback = callback


class ClientGameLoop:
    """
    客户端游戏循环
    整合输入、网络、渲染
    """
    
    LOGIC_FPS = 30
    RENDER_FPS = 60
    
    def __init__(self, client: GameClient):
        """
        初始化游戏循环
        
        Args:
            client: 游戏客户端
        """
        self.client = client
        self.logic_frame_time = 1000 // self.LOGIC_FPS  # ms
        self.running = False
        
        # 回调
        self.on_logic_update: Optional[Callable] = None
        self.on_render: Optional[Callable] = None
    
    async def run(self):
        """运行游戏循环"""
        self.running = True
        
        logic_accumulator = 0.0
        last_time = time.time() * 1000
        
        while self.running and self.client.connected:
            current_time = time.time() * 1000
            delta_time = current_time - last_time
            last_time = current_time
            
            # 限制最大帧时间
            delta_time = min(delta_time, 100)
            
            logic_accumulator += delta_time
            
            # 固定步长逻辑更新
            while logic_accumulator >= self.logic_frame_time:
                await self._update_logic()
                logic_accumulator -= self.logic_frame_time
            
            # 可变步长渲染
            interpolation = logic_accumulator / self.logic_frame_time
            await self._render(interpolation)
            
            # 控制帧率
            await asyncio.sleep(1.0 / self.RENDER_FPS)
    
    async def _update_logic(self):
        """更新逻辑帧"""
        # 获取并执行帧
        frame = self.client.get_next_executable_frame()
        
        if frame:
            # 应用帧输入到游戏状态
            if self.on_logic_update:
                await self.on_logic_update(frame)
            
            # 推进游戏状态
            self.client.game_state.advance_frame()
    
    async def _render(self, interpolation: float):
        """渲染"""
        if self.on_render:
            await self.on_render(interpolation)
    
    def stop(self):
        """停止游戏循环"""
        self.running = False


# 示例用法
async def example_client():
    """客户端示例"""
    client = GameClient()
    
    # 连接服务器
    connected = await client.connect(
        'ws://localhost:8765',
        'player_1',
        'room_001'
    )
    
    if not connected:
        print("Failed to connect")
        return
    
    # 设置帧回调
    async def on_frame(frame):
        print(f"Received frame {frame.frame_id}")
    
    client.on_frame(on_frame)
    
    # 运行游戏循环
    game_loop = ClientGameLoop(client)
    
    # 模拟输入
    from core.input import InputFlags
    
    async def send_inputs():
        while client.connected:
            client.set_input(InputFlags.MOVE_RIGHT)
            await client.send_input()
            await asyncio.sleep(1.0 / 30)
    
    asyncio.create_task(send_inputs())
    
    await game_loop.run()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_client())
