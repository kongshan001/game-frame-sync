"""
Frame synchronization game server
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import time
import logging
from typing import Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import msgpack
import websockets

from core.frame import FrameEngine, Frame
from core.state import GameState
from core.input import InputValidator

logger = logging.getLogger(__name__)


# ==================== 安全组件 ====================

class RateLimiter:
    """速率限制器"""
    
    def __init__(self, max_requests: int = 100, window: float = 1.0):
        self.max_requests = max_requests
        self.window = window
        self.requests: Dict[str, deque] = {}
    
    def is_allowed(self, player_id: str) -> bool:
        """检查是否允许请求"""
        now = time.time()
        
        if player_id not in self.requests:
            self.requests[player_id] = deque()
        
        # 清理过期记录
        while self.requests[player_id] and now - self.requests[player_id][0] > self.window:
            self.requests[player_id].popleft()
        
        if len(self.requests[player_id]) >= self.max_requests:
            return False
        
        self.requests[player_id].append(now)
        return True


class MessageValidator:
    """消息验证器"""
    
    MAX_MESSAGE_SIZE = 10 * 1024  # 10KB
    ALLOWED_TYPES = {'input', 'leave', 'auth', 'reconnect'}
    
    @classmethod
    def validate(cls, message: bytes) -> Optional[dict]:
        """验证消息格式"""
        # 大小限制
        if len(message) > cls.MAX_MESSAGE_SIZE:
            logger.warning(f"Message too large: {len(message)} bytes")
            return None
        
        try:
            data = msgpack.unpackb(message, raw=False)
        except Exception as e:
            logger.warning(f"Invalid msgpack format: {e}")
            return None
        
        # 类型检查
        if not isinstance(data, dict):
            return None
        
        msg_type = data.get('type')
        if msg_type not in cls.ALLOWED_TYPES:
            return None
        
        payload = data.get('payload', {})
        if not isinstance(payload, dict):
            return None
        
        return data


# ==================== 数据类 ====================

@dataclass
class Player:
    """玩家连接信息"""
    player_id: str
    room_id: str
    websocket: any
    last_input_frame: int = -1
    connected_at: float = 0.0
    message_count: int = 0


@dataclass
class GameRoom:
    """游戏房间"""
    room_id: str
    players: Set[str]
    frame_engine: FrameEngine
    game_state: GameState
    created_at: float
    is_started: bool = False
    start_frame: int = 0


# ==================== 服务器类 ====================

class GameServer:
    """
    帧同步游戏服务器
    负责房间管理、帧同步、玩家连接
    """
    
    FRAME_RATE = 30  # 30 FPS
    FRAME_TIME = 1.0 / FRAME_RATE
    
    # 安全配置
    MAX_INPUT_SIZE = 1024  # 1KB
    MAX_FRAME_AHEAD = 100  # 最大超前帧数
    
    def __init__(self, config: dict = None):
        """
        初始化服务器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 房间和玩家管理
        self.rooms: Dict[str, GameRoom] = {}
        self.players: Dict[str, Player] = {}
        self.connections: Dict[str, str] = {}  # websocket id -> player_id
        
        # 配置
        self.max_players_per_room = self.config.get('max_players', 4)
        self.frame_timeout = self.config.get('frame_timeout', 1.0)
        
        # 安全组件
        self.rate_limiter = RateLimiter(
            max_requests=self.config.get('max_requests_per_second', 100),
            window=1.0
        )
        self.input_validator = InputValidator()
        
        # 服务器状态
        self.running = False
        self.frame_task = None
        self.current_frame = 0
    
    async def start(self, host: str = '0.0.0.0', port: int = 8765):
        """
        启动服务器
        
        Args:
            host: 监听地址
            port: 监听端口
        """
        logger.info(f"Starting server on {host}:{port}")
        self.running = True
        
        # 启动帧循环
        self.frame_task = asyncio.create_task(self._frame_loop())
        
        # 启动 WebSocket 服务
        async with websockets.serve(
            self._handle_connection,
            host,
            port,
            ping_interval=20,
            ping_timeout=10
        ):
            logger.info("Server started")
            await self._wait_shutdown()
    
    async def _handle_connection(self, websocket, path):
        """处理客户端连接"""
        player_id = None
        ws_id = str(id(websocket))
        
        try:
            # 等待认证消息
            auth_msg = await asyncio.wait_for(
                websocket.recv(),
                timeout=5.0
            )
            
            player_id = await self._authenticate(auth_msg, websocket)
            
            if not player_id:
                await websocket.close(4001, "Authentication failed")
                return
            
            # 保存连接
            self.connections[ws_id] = player_id
            
            logger.info(f"Player {self._anonymize(player_id)} connected")
            
            # 消息循环
            async for message in websocket:
                await self._handle_message(player_id, message)
                
        except asyncio.TimeoutError:
            await websocket.close(4002, "Authentication timeout")
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            if player_id:
                await self._handle_disconnect(player_id)
            if ws_id in self.connections:
                del self.connections[ws_id]
    
    def _anonymize(self, identifier: str) -> str:
        """匿名化标识符"""
        import hashlib
        return hashlib.sha256(identifier.encode()).hexdigest()[:8]
    
    async def _authenticate(self, message: bytes, websocket) -> Optional[str]:
        """认证玩家"""
        # 验证消息格式
        data = MessageValidator.validate(message)
        if not data or data.get('type') != 'auth':
            return None
        
        payload = data.get('payload', {})
        player_id = payload.get('player_id')
        room_id = payload.get('room_id')
        
        if not player_id or not room_id:
            return None
        
        # 验证 ID 格式
        if not isinstance(player_id, str) or len(player_id) > 64:
            return None
        if not isinstance(room_id, str) or len(room_id) > 64:
            return None
        
        # 创建或加入房间
        success = await self._join_room(player_id, room_id, websocket)
        
        return player_id if success else None
    
    async def _join_room(self, player_id: str, room_id: str, websocket) -> bool:
        """加入房间"""
        # 创建房间（如果不存在）
        if room_id not in self.rooms:
            self.rooms[room_id] = GameRoom(
                room_id=room_id,
                players=set(),
                frame_engine=FrameEngine(player_count=self.max_players_per_room),
                game_state=GameState(),
                created_at=time.time()
            )
        
        room = self.rooms[room_id]
        
        # 检查房间是否已满
        if len(room.players) >= self.max_players_per_room:
            await websocket.close(4003, "Room is full")
            return False
        
        # 添加玩家
        room.players.add(player_id)
        self.players[player_id] = Player(
            player_id=player_id,
            room_id=room_id,
            websocket=websocket,
            connected_at=time.time()
        )
        
        # 通知房间内其他玩家
        await self._broadcast_to_room(room_id, {
            'type': 'player_joined',
            'payload': {
                'player_id': player_id,
                'player_count': len(room.players)
            }
        }, exclude_player=player_id)
        
        # 发送加入成功消息
        await self._send_to_player(player_id, {
            'type': 'join_success',
            'payload': {
                'room_id': room_id,
                'player_id': player_id,
                'player_count': len(room.players),
                'players': list(room.players)
            }
        })
        
        logger.info(f"Player {self._anonymize(player_id)} joined room {self._anonymize(room_id)}")
        return True
    
    async def _handle_message(self, player_id: str, message: bytes):
        """处理玩家消息"""
        # 速率限制
        if not self.rate_limiter.is_allowed(player_id):
            logger.warning(f"Rate limit exceeded for {self._anonymize(player_id)}")
            return
        
        # 验证消息
        data = MessageValidator.validate(message)
        if not data:
            logger.warning(f"Invalid message from {self._anonymize(player_id)}")
            return
        
        msg_type = data.get('type')
        payload = data.get('payload', {})
        
        # 更新消息计数
        if player_id in self.players:
            self.players[player_id].message_count += 1
        
        if msg_type == 'input':
            await self._handle_input(player_id, payload)
        elif msg_type == 'leave':
            await self._handle_leave(player_id)
        elif msg_type == 'reconnect':
            await self._handle_reconnect(player_id, payload)
    
    async def _handle_input(self, player_id: str, payload: dict):
        """处理玩家输入"""
        player = self.players.get(player_id)
        if not player:
            return
        
        room = self.rooms.get(player.room_id)
        if not room:
            return
        
        # 验证 payload
        frame_id = payload.get('frame_id')
        if not isinstance(frame_id, int):
            return
        if frame_id < 0 or frame_id > self.current_frame + self.MAX_FRAME_AHEAD:
            logger.warning(f"Invalid frame_id {frame_id} from {self._anonymize(player_id)}")
            return
        
        # 验证输入数据
        input_data = payload.get('input_data', b'')
        if not isinstance(input_data, bytes):
            return
        if len(input_data) > self.MAX_INPUT_SIZE:
            logger.warning(f"Input data too large from {self._anonymize(player_id)}")
            return
        
        # 防止重放攻击
        if frame_id <= player.last_input_frame:
            logger.warning(f"Duplicate frame_id {frame_id} from {self._anonymize(player_id)}")
            return
        
        # 解析玩家ID（从 player_id 字符串中提取数字）
        try:
            numeric_id = int(player_id.split('_')[-1]) if '_' in player_id else hash(player_id) % 1000
        except ValueError:
            numeric_id = hash(player_id) % 1000
        
        # 添加到帧引擎
        room.frame_engine.add_input(frame_id, numeric_id, input_data)
        player.last_input_frame = frame_id
    
    async def _handle_leave(self, player_id: str):
        """处理玩家离开"""
        await self._handle_disconnect(player_id)
    
    async def _handle_reconnect(self, player_id: str, payload: dict):
        """处理重连请求"""
        player = self.players.get(player_id)
        if not player:
            return
        
        last_frame = payload.get('last_frame', 0)
        room = self.rooms.get(player.room_id)
        
        if room:
            # 发送缺失的帧数据
            frames_to_send = []
            for fid in range(last_frame + 1, room.frame_engine.get_current_frame_id()):
                frame = room.frame_engine.get_frame(fid)
                if frame:
                    frames_to_send.append({
                        'frame_id': frame.frame_id,
                        'inputs': {str(k): v for k, v in frame.inputs.items()},
                        'confirmed': frame.confirmed
                    })
            
            await self._send_to_player(player_id, {
                'type': 'sync_frames',
                'payload': {
                    'frames': frames_to_send,
                    'current_frame': room.frame_engine.get_current_frame_id()
                }
            })
    
    async def _handle_disconnect(self, player_id: str):
        """处理玩家断线"""
        player = self.players.get(player_id)
        if not player:
            return
        
        room_id = player.room_id
        room = self.rooms.get(room_id)
        
        if room:
            room.players.discard(player_id)
            
            # 通知其他玩家
            await self._broadcast_to_room(room_id, {
                'type': 'player_left',
                'payload': {'player_id': player_id}
            })
            
            # 如果房间空了，清理
            if not room.players:
                del self.rooms[room_id]
                logger.info(f"Room {self._anonymize(room_id)} cleaned up")
        
        del self.players[player_id]
        logger.info(f"Player {self._anonymize(player_id)} disconnected")
    
    async def _frame_loop(self):
        """帧同步主循环"""
        logger.info("Frame loop started")
        
        while self.running:
            frame_start = time.time()
            
            # 处理所有房间
            for room_id, room in list(self.rooms.items()):
                try:
                    frame = room.frame_engine.tick()
                    
                    if frame:
                        # 广播帧数据
                        await self._broadcast_frame(room_id, frame)
                        
                        # 检查是否可以开始游戏
                        if not room.is_started and len(room.players) >= 2:
                            room.is_started = True
                            room.start_frame = frame.frame_id
                            await self._broadcast_to_room(room_id, {
                                'type': 'game_start',
                                'payload': {'start_frame': room.start_frame}
                            })
                    
                except Exception as e:
                    logger.error(f"Frame loop error in room {room_id}: {e}")
            
            self.current_frame += 1
            
            # 精确帧率控制
            elapsed = time.time() - frame_start
            sleep_time = self.FRAME_TIME - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
    
    async def _broadcast_frame(self, room_id: str, frame: Frame):
        """广播帧数据"""
        message = msgpack.packb({
            'type': 'game_frame',
            'payload': {
                'frame_id': frame.frame_id,
                'inputs': {str(k): v for k, v in frame.inputs.items()},
                'confirmed': frame.confirmed
            }
        })
        
        await self._broadcast_to_room(room_id, message, binary=True)
    
    async def _broadcast_to_room(self, room_id: str, message, binary=False, exclude_player=None):
        """向房间广播消息"""
        room = self.rooms.get(room_id)
        if not room:
            return
        
        tasks = []
        for player_id in room.players:
            if player_id == exclude_player:
                continue
            
            player = self.players.get(player_id)
            if player and player.websocket:
                if binary:
                    tasks.append(player.websocket.send(message))
                else:
                    tasks.append(player.websocket.send(msgpack.packb(message)))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_to_player(self, player_id: str, message):
        """发送消息给指定玩家"""
        player = self.players.get(player_id)
        if player and player.websocket:
            await player.websocket.send(msgpack.packb(message))
    
    async def _wait_shutdown(self):
        """等待关闭信号"""
        loop = asyncio.get_event_loop()
        stop = loop.create_future()
        
        try:
            import signal
            def signal_handler():
                stop.set_result(None)
            
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
            loop.add_signal_handler(signal.SIGINT, signal_handler)
        except:
            pass
        
        await stop
        self.running = False
        logger.info("Server shutting down...")
    
    def get_stats(self) -> dict:
        """获取服务器统计信息"""
        return {
            'rooms': len(self.rooms),
            'players': len(self.players),
            'current_frame': self.current_frame,
            'room_details': {
                room_id: {
                    'players': len(room.players),
                    'frame': room.frame_engine.get_current_frame_id(),
                    'is_started': room.is_started
                }
                for room_id, room in self.rooms.items()
            }
        }


# 启动入口
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    config = {
        'max_players': 4,
        'frame_timeout': 1.0,
        'max_requests_per_second': 100
    }
    
    server = GameServer(config)
    asyncio.run(server.start())
