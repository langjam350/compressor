import asyncio
import json
import threading
import time
from typing import Callable, Optional

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.session_id import generate_session_id

app = FastAPI()
app.state.query_handler = None
app.state.broadcast_handler = None
# Every unit runs this server, whether or not it currently owns the system,
# so that peers can probe /health at any time. `owner` is what distinguishes
# the unit actually doing the host's job from one that is merely alive.
app.state.unit_name = None
app.state.owner = False
app.state.priority = None
app.state.session_id = None
_connected_clients: list[WebSocket] = []
# One entry per in-flight /broadcast call, keyed by request_id, so a
# "speak_response" arriving on /ws can be routed back to the HTTP caller
# that's still waiting on it instead of being fanned out to every client.
_pending_broadcasts: dict[str, "asyncio.Queue"] = {}


class QueryRequest(BaseModel):
    unit_name: str
    text: str


class QueryResponse(BaseModel):
    response: str


class BroadcastRequest(BaseModel):
    text: str
    timeout: float = 10.0


class BroadcastReply(BaseModel):
    unit: str
    text: str


class BroadcastResponse(BaseModel):
    request_id: str
    replies: list[BroadcastReply]


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


@app.get("/health")
def health():
    """Liveness plus ownership, for the cluster election (see src/cluster.py).

    connected_followers excludes the unit's own loopback self-loop (see
    broadcast_endpoint) so it reflects actual remote units connected over
    /ws — a quick live check for "is anyone actually following me right
    now", independent of the action log."""
    followers = sum(
        1 for c in _connected_clients
        if not (c.client and c.client.host in ("127.0.0.1", "::1"))
    )
    return {
        "unit_name": app.state.unit_name,
        "owner": bool(app.state.owner),
        "priority": app.state.priority,
        "session_id": app.state.session_id,
        "connected_followers": followers,
    }


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


@app.post("/broadcast", response_model=BroadcastResponse)
async def broadcast_endpoint(req: BroadcastRequest):
    """Ask every unit to speak `text` aloud, and collect whatever voice
    reply (if any) comes back from each one within `timeout` seconds.

    One request, every unit — the host relays over /ws to followers and
    runs `broadcast_handler` directly for itself. Unlike the generic /ws
    relay (which excludes the sender's own connection), this push comes
    from an HTTP call with no "sender" connection to exclude, so the
    host's own self-loop client (it points its own NetworkClient at
    127.0.0.1 while it owns the system — see Assistant._become_owner)
    would otherwise get the WS message AND the direct handler call,
    double-speaking. Skip any loopback-connected client explicitly;
    only genuine remote followers connect from a real LAN address."""
    request_id = generate_session_id()
    queue: asyncio.Queue = asyncio.Queue()
    _pending_broadcasts[request_id] = queue

    message = json.dumps({"type": "speak_request", "request_id": request_id, "text": req.text})
    sent_to = 0
    for client in list(_connected_clients):
        if client.client and client.client.host in ("127.0.0.1", "::1"):
            continue
        try:
            await client.send_text(message)
            sent_to += 1
        except Exception as e:
            # A send failure means the connection is dead even though it's
            # still sitting in _connected_clients (health's connected_followers
            # counts presence, not liveness) — reap it here the same way the
            # generic /ws relay loop does, so a stale connection stops being
            # silently counted as a working follower.
            print(f"[Broadcast] Dropping dead connection {client.client}: {e}")
            if client in _connected_clients:
                _connected_clients.remove(client)
    print(f"[Broadcast] {request_id}: pushed speak_request to {sent_to} remote unit(s).")

    handler = app.state.broadcast_handler
    if handler is not None:
        loop = asyncio.get_event_loop()
        local_unit = app.state.unit_name

        def _run_local():
            try:
                reply = handler(req.text)
            except Exception:
                reply = None
            if reply:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"unit": local_unit, "text": reply}), loop
                )

        threading.Thread(target=_run_local, daemon=True).start()

    replies = []
    deadline = time.monotonic() + req.timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                replies.append(await asyncio.wait_for(queue.get(), timeout=remaining))
            except asyncio.TimeoutError:
                break
    finally:
        _pending_broadcasts.pop(request_id, None)

    return BroadcastResponse(
        request_id=request_id,
        replies=[BroadcastReply(**r) for r in replies],
    )


async def _route_speak_response(raw_message: str) -> bool:
    """If `raw_message` is a speak_response for an in-flight /broadcast,
    deliver it to that call's queue and return True (handled — don't relay
    it to other clients). Otherwise return False, unchanged."""
    try:
        parsed = json.loads(raw_message)
    except Exception:
        return False
    if not isinstance(parsed, dict) or parsed.get("type") != "speak_response":
        return False
    queue = _pending_broadcasts.get(parsed.get("request_id"))
    if queue is not None:
        await queue.put({"unit": parsed.get("unit"), "text": parsed.get("text")})
    return True


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connected_clients.append(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if await _route_speak_response(message):
                continue
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
    broadcast_handler: Optional[Callable[[str], Optional[str]]] = None,
):
    if query_handler is not None:
        app.state.query_handler = query_handler
    if broadcast_handler is not None:
        app.state.broadcast_handler = broadcast_handler
    uvicorn.run(app, host=host, port=port, log_level="warning")
