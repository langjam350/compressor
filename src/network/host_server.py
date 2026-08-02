from typing import Callable, Optional

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

app = FastAPI()
app.state.query_handler = None
_connected_clients: list[WebSocket] = []


class QueryRequest(BaseModel):
    unit_name: str
    text: str


class QueryResponse(BaseModel):
    response: str


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


@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    handler = app.state.query_handler
    if handler is None:
        return QueryResponse(response="Host is not ready to process queries yet.")
    try:
        result = handler(req.unit_name, req.text)
        return QueryResponse(response=str(result) if result is not None else "Sorry, something went wrong.")
    except Exception:
        return QueryResponse(response="Sorry, something went wrong.")


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


def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    query_handler: Optional[Callable[[str, str], str]] = None,
):
    app.state.query_handler = query_handler
    uvicorn.run(app, host=host, port=port, log_level="warning")
