import asyncio
import json
import threading
import time
from typing import Callable, Optional
import httpx
import websockets


class NetworkClient:
    def __init__(self, host_ip: str, host_port: int = 8765):
        self._host_ip = host_ip
        self._host_port = host_port
        self._base = f"http://{host_ip}:{host_port}"
        self._ws_url = f"ws://{host_ip}:{host_port}/ws"
        self._on_message: Optional[Callable[[dict], None]] = None
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_host(self, host_ip: str, host_port: Optional[int] = None) -> bool:
        """Point this client at a different host after an ownership change.

        Closes the current WebSocket so the listen loop reconnects to the new
        URL on its next pass. Returns True when the host actually changed.
        """
        port = self._host_port if host_port is None else host_port
        if host_ip == self._host_ip and port == self._host_port:
            return False

        self._host_ip = host_ip
        self._host_port = port
        self._base = f"http://{host_ip}:{port}"
        self._ws_url = f"ws://{host_ip}:{port}/ws"

        ws, loop = self._ws, self._loop
        if ws is not None and loop is not None:
            # _listen() re-reads self._ws_url every pass, so ending the current
            # connection is all it takes to migrate.
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception as e:
                print(f"[Network] Could not close old WebSocket: {e}")
        return True

    def get_info(self) -> dict:
        try:
            resp = httpx.get(f"{self._base}/info", timeout=5.0)
            return resp.json()
        except Exception:
            return {}

    def query(self, unit_name: str, text: str) -> str:
        try:
            resp = httpx.post(
                f"{self._base}/query",
                json={"unit_name": unit_name, "text": text},
                timeout=60.0,
            )
            return resp.json()["response"]
        except Exception:
            return "Sorry, I can't reach the host right now."

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
        retry_delay = 2
        while True:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    retry_delay = 2  # reset on successful connection
                    async for raw in ws:
                        if self._on_message:
                            try:
                                self._on_message(json.loads(raw))
                            except Exception:
                                pass
            except Exception as e:
                print(f"[Network] WebSocket disconnected: {e}")
            self._ws = None
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)

    def broadcast(self, payload: dict):
        """Send a JSON message to all other connected clients via the Host."""
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(payload)), self._loop
            )
