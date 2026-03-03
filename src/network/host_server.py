import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()
_connected_clients: list[WebSocket] = []


async def get_location() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://ipinfo.io/json", timeout=5.0)
        return resp.json()


@app.get("/info")
async def info():
    try:
        loc = await get_location()
        return {
            "city": loc.get("city", "Unknown"),
            "region": loc.get("region", "Unknown"),
            "country": loc.get("country", "Unknown"),
            "timezone": loc.get("timezone", "Unknown"),
        }
    except Exception:
        return {"city": "Unknown", "region": "Unknown", "country": "Unknown", "timezone": "Unknown"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connected_clients.append(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            for client in list(_connected_clients):
                if client is not websocket:
                    try:
                        await client.send_text(message)
                    except Exception:
                        _connected_clients.remove(client)
    except WebSocketDisconnect:
        if websocket in _connected_clients:
            _connected_clients.remove(websocket)


def run_server(host: str = "0.0.0.0", port: int = 8765):
    uvicorn.run(app, host=host, port=port, log_level="warning")
