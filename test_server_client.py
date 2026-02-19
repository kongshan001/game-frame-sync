#!/usr/bin/env python3
"""
服务器/客户端集成测试
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import websockets
import msgpack
import time
import signal

# 全局变量
server_running = True
clients_connected = []

async def handle_client(websocket):
    """处理客户端连接"""
    client_id = len(clients_connected)
    clients_connected.append(websocket)
    print(f"[服务器] 客户端 {client_id} 已连接")
    
    try:
        # 等待认证
        data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        msg = msgpack.unpackb(data, raw=False)
        print(f"[服务器] 收到消息: {msg}")
        
        # 发送确认
        response = msgpack.packb({
            'type': 'joined',
            'payload': {'player_id': f'player_{client_id}', 'room_id': 'test_room'}
        })
        await websocket.send(response)
        
        # 模拟帧同步
        frame_id = 0
        while server_running:
            frame = msgpack.packb({
                'type': 'game_frame',
                'payload': {
                    'frame_id': frame_id,
                    'inputs': {},
                    'confirmed': True
                }
            })
            await websocket.send(frame)
            frame_id += 1
            await asyncio.sleep(0.033)  # 30fps
            
    except asyncio.TimeoutError:
        print(f"[服务器] 客户端 {client_id} 认证超时")
    except websockets.exceptions.ConnectionClosed:
        print(f"[服务器] 客户端 {client_id} 断开连接")
    except Exception as e:
        print(f"[服务器] 客户端 {client_id} 错误: {e}")

async def test_client(client_id: int, server_url: str = "ws://127.0.0.1:8765"):
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
            
            while time.time() - start_time < 5:  # 运行5秒
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = msgpack.unpackb(data, raw=False)
                    
                    if msg.get('type') == 'joined':
                        print(f"[客户端 {client_id}] 加入成功!")
                    elif msg.get('type') == 'game_frame':
                        frame_count += 1
                        if frame_count % 30 == 0:
                            print(f"[客户端 {client_id}] 收到 {frame_count} 帧")
                    
                except asyncio.TimeoutError:
                    pass
            
            print(f"[客户端 {client_id}] 测试完成，共收到 {frame_count} 帧")
            return True
            
    except Exception as e:
        print(f"[客户端 {client_id}] 错误: {e}")
        return False

async def run_server():
    """运行服务器"""
    global server_running
    
    print("[服务器] 启动中...")
    
    async with websockets.serve(handle_client, "127.0.0.1", 8765):
        print("[服务器] 监听 127.0.0.1:8765")
        
        # 等待一段时间
        await asyncio.sleep(8)
        
    print("[服务器] 关闭")

async def main():
    """主测试函数"""
    print("=" * 50)
    print("帧同步服务器/客户端集成测试")
    print("=" * 50)
    
    # 启动服务器（后台任务）
    server_task = asyncio.create_task(run_server())
    
    # 等待服务器启动
    await asyncio.sleep(1)
    
    # 启动多个客户端
    print("\n--- 启动3个测试客户端 ---\n")
    
    results = await asyncio.gather(
        test_client(1),
        test_client(2),
        test_client(3),
    )
    
    # 等待服务器关闭
    await server_task
    
    # 输出结果
    print("\n" + "=" * 50)
    print("测试结果:")
    print(f"  客户端1: {'✓ 成功' if results[0] else '✗ 失败'}")
    print(f"  客户端2: {'✓ 成功' if results[1] else '✗ 失败'}")
    print(f"  客户端3: {'✓ 成功' if results[2] else '✗ 失败'}")
    print("=" * 50)

if __name__ == '__main__':
    asyncio.run(main())
