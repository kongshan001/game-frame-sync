#!/usr/bin/env python3
"""
测试客户端 - 用于测试服务器连接
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import websockets
import msgpack
import time

async def test_client(client_id: int, server_url: str = "ws://localhost:8765"):
    """测试客户端"""
    print(f"[客户端 {client_id}] 连接到 {server_url}...")
    
    try:
        async with websockets.connect(server_url) as ws:
            print(f"[客户端 {client_id}] 连接成功!")
            
            # 发送加入请求
            join_msg = msgpack.packb({
                'type': 'join',
                'payload': {
                    'player_id': f'player_{client_id}',
                    'room_id': 'test_room'
                }
            })
            await ws.send(join_msg)
            print(f"[客户端 {client_id}] 发送加入请求")
            
            # 接收消息
            frame_count = 0
            start_time = time.time()
            
            while time.time() - start_time < 10:  # 运行10秒
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = msgpack.unpackb(data, raw=False)
                    
                    if msg.get('type') == 'joined':
                        print(f"[客户端 {client_id}] 加入成功! 玩家ID: {msg['payload']['player_id']}")
                    elif msg.get('type') == 'game_start':
                        print(f"[客户端 {client_id}] 游戏开始! 起始帧: {msg['payload']['start_frame']}")
                    elif msg.get('type') == 'game_frame':
                        frame_count += 1
                        if frame_count % 30 == 0:
                            print(f"[客户端 {client_id}] 收到帧 {msg['payload']['frame_id']}, 总计: {frame_count}")
                    
                except asyncio.TimeoutError:
                    # 发送心跳/输入
                    input_msg = msgpack.packb({
                        'type': 'input',
                        'payload': {
                            'frame_id': frame_count,
                            'input_data': b'test_input'
                        }
                    })
                    await ws.send(input_msg)
            
            print(f"[客户端 {client_id}] 测试完成，共收到 {frame_count} 帧")
            
    except Exception as e:
        print(f"[客户端 {client_id}] 错误: {e}")

async def main():
    """启动多个测试客户端"""
    print("=== 开始多客户端测试 ===\n")
    
    # 同时启动3个客户端
    tasks = [
        test_client(1),
        test_client(2),
        test_client(3),
    ]
    
    await asyncio.gather(*tasks)
    
    print("\n=== 测试完成 ===")

if __name__ == '__main__':
    asyncio.run(main())
