"""
Frame synchronization game server
"""

import asyncio
import time
import logging
from typing import Dict, Set, Optional
from dataclasses import dataclass
import msgpack
import websockets

from core.frame import FrameEngine, Frame
from core.state import GameState

logger = logging.getLogger(__name__)


@dataclass
class Player:
    """玩家连接信息"""
    player_id: str
    room_id: str
    websocket: any
    last_input_frame: int = -1
    connected_at: float = 0.0


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


class GameServer:
    """
    帧同步游戏服务器
    负责房间管理、帧同步、玩家连接
    """
    
    FRAME_RATE = 30  # 30 FPS
    FRAME_TIME = 1.0 / FRAME_RATE
    
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
        self.connections: Dict[str, any] = {}  # websocket -> player_id
        
        # 配置
        self.max_players_per_room = self.config.get('max_players', 4)
        self.frame_timeout = self.config.get('frame_timeout', 1.0)  # 1秒超时
        
        # 服务器状态
        self.running = False
        self.frame_task = None
    
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
            self.connections[websocket] = player_id
            
            logger.info(f"Player {player_id} connected")
            
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
            if websocket in self.connections:
                del self.connections[websocket]
    
    async def _authenticate(self, message: bytes, websocket) -> Optional[str]:
        """认证玩家"""
        try:
            data = msgpack.unpackb(message, raw=False)
            player_id = data.get('player_id')
            room_id = data.get('room_id')
            
            if not player_id or not room_id:
                return None
            
            # 创建或加入房间
            await self._join_room(player_id, room_id, websocket)
            
            return player_id
            
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None
    
    async def _join_room(self, player_id: str, room_id: str, websocket):
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
            return
        
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
        
        logger.info(f"Player {player_id} joined room {room_id}")
    
    async def _handle_message(self, player_id: str, message: bytes):
        """处理玩家消息"""
        try:
            data = msgpack.unpackb(message, raw=False)
            msg_type = data.get('type')
            payload = data.get('payload', {})
            
            if msg_type == 'input':
                await self._handle_input(player_id, payload)
            elif msg_type == 'leave':
                await self._handle_leave(player_id)
            
        except Exception as e:
            logger.error(f"Message handling error: {e}")
    
    async def _handle_input(self, player_id: str, payload: dict):
        """处理玩家输入"""
        player = self.players.get(player_id)
        if not player:
            return
        
        room = self.rooms.get(player.room_id)
        if not room:
            return
        
        frame_id = payload.get('frame_id')
        input_data = payload.get('input_data', b'')
        
        # 添加到帧引擎
        room.frame_engine.add_input(
            frame_id, 
            int(player_id.split('_')[-1]) if '_' in player_id else hash(player_id) % 1000,
            input_data
        )
        
        player.last_input_frame = frame_id
    
    async def _handle_leave(self, player_id: str):
        """处理玩家离开"""
        await self._handle_disconnect(player_id)
    
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
                logger.info(f"Room {room_id} cleaned up")
        
        del self.players[player_id]
        logger.info(f"Player {player_id} disconnected")
    
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
        'frame_timeout': 1.0
    }
    
    server = GameServer(config)
    asyncio.run(server.start())
