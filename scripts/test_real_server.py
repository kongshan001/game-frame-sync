#!/usr/bin/env python3
"""
真实服务器测试
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import websockets
import msgpack
import time

async def test_real_server():
    """测试真实服务器"""
    print("=" * 50)
    print("真实服务器测试")
    print("=" * 50)
    
    # 导入服务器
    from server.main import GameServer
    
    config = {
        'max_players': 4,
        'frame_timeout': 1.0,
        'max_requests_per_second': 100
    }
    
    server = GameServer(config)
    server.running = True
    
    # 启动服务器
    async def run_server():
        async with websockets.serve(
            server._handle_connection,
            '127.0.0.1',
            8767,
            ping_interval=20,
            ping_timeout=10
        ):
            print("[服务器] 监听 127.0.0.1:8767")
            # 启动帧循环
            frame_task = asyncio.create_task(server._frame_loop())
            
            # 等待测试完成
            await asyncio.sleep(8)
            
            server.running = False
            frame_task.cancel()
            print("[服务器] 关闭")
    
    # 客户端测试
    async def test_client(cid):
        url = 'ws://127.0.0.1:8767'
        print(f"[客户端 {cid}] 连接到 {url}...")
        
        try:
            async with websockets.connect(url) as ws:
                print(f"[客户端 {cid}] 连接成功")
                
                # 发送认证消息 (type: 'auth', 不是 'join')
                auth_msg = msgpack.packb({
                    'type': 'auth',
                    'payload': {
                        'player_id': f'player_{cid}',
                        'room_id': 'test_room'
                    }
                })
                await ws.send(auth_msg)
                print(f"[客户端 {cid}] 发送认证请求")
                
                # 接收消息
                frames = 0
                joined = False
                game_started = False
                start = asyncio.get_event_loop().time()
                
                while asyncio.get_event_loop().time() - start < 6:
                    try:
                        data = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        msg = msgpack.unpackb(data, raw=False)
                        msg_type = msg.get('type')
                        
                        if msg_type == 'join_success':
                            joined = True
                            print(f"[客户端 {cid}] 加入成功! 房间: {msg['payload']['room_id']}")
                        elif msg_type == 'game_start':
                            game_started = True
                            print(f"[客户端 {cid}] 游戏开始!")
                        elif msg_type == 'game_frame':
                            frames += 1
                            if frames % 30 == 0:
                                print(f"[客户端 {cid}] 收到帧 {msg['payload']['frame_id']}")
                        elif msg_type == 'player_joined':
                            print(f"[客户端 {cid}] 收到玩家加入通知: {msg['payload']['player_id']}")
                            
                    except asyncio.TimeoutError:
                        # 发送输入
                        if joined:
                            input_msg = msgpack.packb({
                                'type': 'input',
                                'payload': {
                                    'frame_id': frames,
                                    'input_data': b'\x01\x02'
                                }
                            })
                            await ws.send(input_msg)
                
                print(f"[客户端 {cid}] 测试完成: 加入={joined}, 游戏开始={game_started}, 帧={frames}")
                return {'joined': joined, 'started': game_started, 'frames': frames}
                
        except Exception as e:
            print(f"[客户端 {cid}] 错误: {e}")
            return {'joined': False, 'started': False, 'frames': 0}
    
    # 并行运行
    server_task = asyncio.create_task(run_server())
    await asyncio.sleep(1)
    
    print("\n--- 启动客户端测试 ---\n")
    
    results = await asyncio.gather(
        test_client(1),
        test_client(2),
        test_client(3),
    )
    
    await server_task
    
    # 输出结果
    print("\n" + "=" * 50)
    print("测试结果:")
    for i, r in enumerate(results, 1):
        status = "✓" if r['joined'] and r['started'] and r['frames'] > 0 else "✗"
        print(f"  客户端 {i}: {status}")
        print(f"    - 加入成功: {r['joined']}")
        print(f"    - 游戏开始: {r['started']}")
        print(f"    - 收到帧数: {r['frames']}")
    print("=" * 50)
    
    # 总结
    all_success = all(r['joined'] and r['started'] and r['frames'] > 0 for r in results)
    return all_success

if __name__ == '__main__':
    success = asyncio.run(test_real_server())
    sys.exit(0 if success else 1)
