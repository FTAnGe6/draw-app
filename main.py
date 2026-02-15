from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import random
import os

app = FastAPI()

rooms = {}
ROLES = ["刺客", "法师", "射手", "辅助", "战士"]

@app.get("/")
async def get():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# 注意这里增加了 client_id 参数，用来接收玩家输入的昵称
@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, client_id: str):
    await websocket.accept()

    if room_id not in rooms:
        rooms[room_id] = {
            "connections": [],
            "host_ws": websocket 
        }
    
    room = rooms[room_id]

    # 1. 检查人数
    if len(room["connections"]) >= 5:
        await websocket.send_json({"type": "error", "msg": "房间已满，最多5人"})
        await websocket.close()
        return

    # 2. 检查昵称是否重复
    for c in room["connections"]:
        if c["player_id"] == client_id:
            await websocket.send_json({"type": "error", "msg": f"昵称 '{client_id}' 已被占用，请换一个"})
            await websocket.close()
            return

    # 加入房间
    player_info = {"ws": websocket, "player_id": client_id}
    room["connections"].append(player_info)

    is_host = (websocket == room["host_ws"])
    await websocket.send_json({
        "type": "welcome",
        "player_id": client_id,
        "is_host": is_host
    })

    # 广播更新函数
    async def broadcast_update():
        if room_id not in rooms: return
        players_list = [c["player_id"] for c in room["connections"]]
        host_id = [c["player_id"] for c in room["connections"] if c["ws"] == room["host_ws"]][0] if room["host_ws"] else ""
        for c in room["connections"]:
            try:
                await c["ws"].send_json({"type": "update", "players": players_list, "host": host_id})
            except:
                pass

    await broadcast_update()

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            # --- 动作：开始发牌 ---
            if action == "start":
                if websocket != room["host_ws"]:
                    await websocket.send_json({"type": "error", "msg": "只有房主才能发牌哦"})
                    continue
                
                num_players = len(room["connections"])
                shuffled_roles = ROLES[:num_players]
                random.shuffle(shuffled_roles)

                for i, c in enumerate(room["connections"]):
                    await c["ws"].send_json({
                        "type": "result",
                        "role": shuffled_roles[i]
                    })
            
            # --- 动作：解散房间 ---
            elif action == "destroy":
                if websocket != room["host_ws"]:
                    await websocket.send_json({"type": "error", "msg": "只有房主才能解散房间"})
                    continue
                
                # 通知所有人房间已解散
                for c in room["connections"]:
                    if c["ws"] != websocket: # 房主自己由前端直接跳转，不用发
                        await c["ws"].send_json({"type": "destroyed"})
                    await c["ws"].close()
                
                del rooms[room_id]
                return # 结束当前连接
                
            # --- 动作：退出房间 ---
            elif action == "leave":
                break # 直接跳出循环，触发下方的 disconnect 逻辑

    except WebSocketDisconnect:
        pass

    # --- 玩家断开连接后的清理逻辑（断网、点退出、关网页都会触发） ---
    if room_id in rooms:
        # 将该玩家从列表中移除
        room["connections"] = [c for c in room["connections"] if c["ws"] != websocket]
        
        if not room["connections"]:
            # 人走空了，销毁房间
            del rooms[room_id]
        else:
            # 如果退出的是房主，移交房主权限给第一个加入的人
            if websocket == room["host_ws"]:
                room["host_ws"] = room["connections"][0]["ws"]
                try:
                    # 告诉新房主，你上位了
                    await room["host_ws"].send_json({"type": "become_host"})
                except:
                    pass
            
            # 广播最新房间状态
            await broadcast_update()
