import asyncio
import json
import threading
from typing import Callable, Optional
import httpx
import websockets


class NetworkClient:
    def __init__(self, host_ip: str, host_port: int = 8765):
        self._base = f"http://{host_ip}:{host_port}"
        self._ws_url = f"ws://{host_ip}:{host_port}/ws"
        self._on_message: Optional[Callable[[dict], None]] = None
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def get_info(self) -> dict:
        try:
            resp = httpx.get(f"{self._base}/info", timeout=5.0)
            return resp.json()
        except Exception:
            return {}

    def on_message(self, callback: Callable[[dict], None]):
        """Register a callback for incoming WebSocket messages."""
        self._on_message = callback

    def start_websocket(self):
        """Start WebSocket listener in a background daemon thread."""
        thread = threading.Thread(target=self._run_ws_loop, daemon=True)
        thread.start()

    def _run_ws_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._listen())

    async def _listen(self):
        try:
            async with websockets.connect(self._ws_url) as ws:
                self._ws = ws
                async for raw in ws:
                    if self._on_message:
                        try:
                            self._on_message(json.loads(raw))
                        except Exception:
                            pass
        except Exception as e:
            print(f"[Network] WebSocket disconnected: {e}")

    def broadcast(self, payload: dict):
        """Send a JSON message to all other connected clients via the Host."""
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(payload)), self._loop
            )
