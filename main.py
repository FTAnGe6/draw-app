from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import random
import os

app = FastAPI()

# 存放所有的房间数据。键是房间号，值是房间信息的字典。
rooms = {}

# 待分配的五个角色
ROLES = ["刺客", "法师", "射手", "辅助", "战士"]

# 读取前端页面
@app.get("/")
async def get():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# WebSocket 核心逻辑
@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()

    # 如果房间不存在，就初始化一个
    if room_id not in rooms:
        rooms[room_id] = {
            "connections": [], # 存放玩家的 ws 对象和代号
            "host_ws": websocket, # 第一个进来的设为房主
            "counter": 1 # 用于生成玩家代号
        }
    
    room = rooms[room_id]

    # 限制5个人
    if len(room["connections"]) >= 5:
        await websocket.send_json({"type": "error", "msg": "房间已满，最多5人"})
        await websocket.close()
        return

    # 分配玩家代号
    player_id = f"玩家{room['counter']}"
    room["counter"] += 1
    
    # 将当前用户加入房间记录
    player_info = {"ws": websocket, "player_id": player_id}
    room["connections"].append(player_info)

    # 告诉该用户：欢迎加入，你是不是房主
    is_host = (websocket == room["host_ws"])
    await websocket.send_json({
        "type": "welcome",
        "player_id": player_id,
        "is_host": is_host
    })

    # 广播给所有人：人数有更新了！
    async def broadcast_update():
        players_list = [c["player_id"] for c in room["connections"]]
        host_id = [c["player_id"] for c in room["connections"] if c["ws"] == room["host_ws"]][0] if room["host_ws"] else ""
        for c in room["connections"]:
            await c["ws"].send_json({
                "type": "update",
                "players": players_list,
                "host": host_id
            })

    await broadcast_update()

    try:
        # 持续监听当前用户发来的消息
        while True:
            data = await websocket.receive_json()
            
            # 只有收到房主发来的 "start" 指令，才开始发牌
            if data.get("action") == "start":
                if websocket != room["host_ws"]:
                    await websocket.send_json({"type": "error", "msg": "只有房主才能发牌哦"})
                    continue
                
                num_players = len(room["connections"])
                
                # --- [测试友好提示] ---
                # 为了方便你一个人打开几个浏览器窗口测试，这里目前允许不满 5 人也发牌（会截取前几个角色）。
                # 如果你想严格限制必须 5 个人才能开始，取消下面两行代码的注释即可：
                # if num_players != 5:
                #     await websocket.send_json({"type": "error", "msg": f"当前只有 {num_players} 人，必须凑齐 5 人才能发牌！"})
                #     continue
                
                # 核心发牌逻辑：打乱角色列表
                shuffled_roles = ROLES[:num_players]
                random.shuffle(shuffled_roles)

                # 将打乱后的角色，一对一盲发给对应的玩家
                for i, c in enumerate(room["connections"]):
                    await c["ws"].send_json({
                        "type": "result",
                        "role": shuffled_roles[i]
                    })

    except WebSocketDisconnect:
        # 玩家断开连接（如关掉网页）
        room["connections"] = [c for c in room["connections"] if c["ws"] != websocket]
        
        if not room["connections"]:
            # 如果人都走光了，销毁房间释放内存
            del rooms[room_id]
        else:
            # 如果房主走了，把房主移交给下一个还在房间里的人
            if websocket == room["host_ws"]:
                room["host_ws"] = room["connections"][0]["ws"]
            # 广播最新状态
            await broadcast_update()