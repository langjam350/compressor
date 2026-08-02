import logging
import threading
import time

from src import action_log
from src.config_loader import load_config
from src.stt import SpeechListener
from src.tts import TTSEngine
from src.ai_client import AIClient
from src.integrations.tuya import TuyaController
from src.integrations.spotify import SpotifyController
from src.network.host_server import app, run_server
from src.network.client import NetworkClient
from src.scheduler import Scheduler
from src.tasks import tuya_sync

log = logging.getLogger(__name__)

IDLE_RESET_SECONDS = 30


def build_system_prompt(location: dict, devices: list[dict]) -> str:
    device_names = ", ".join(d["name"] for d in devices) if devices else "none"
    city = location.get("city", "Unknown")
    region = location.get("region", "Unknown")
    tz = location.get("timezone", "Unknown")
    return f"""You are Compressor, a friendly AI voice assistant for the home. Your responses will be spoken aloud, so:
- Be concise (1-3 sentences unless the user asks for detail)
- Avoid markdown, bullet points, or formatting
- Speak naturally

Current location: {city}, {region} (timezone: {tz})
Registered smart home devices: {device_names}

You can control smart home devices and music, but you are also a general-purpose AI assistant. Answer any question the user asks — cooking, trivia, advice, facts, recommendations — just like a knowledgeable friend would. Only use tools when the user wants to control a device or play music.
"""


class Assistant:
    def __init__(self, config_path: str = "config.yaml"):
        self._config = load_config(config_path)
        self._role = self._config["role"]
        self._unit_name = self._config.get("unit_name", "host")
        self._tts = TTSEngine()
        self._listener = SpeechListener(
            self._config["wake_word"],
            on_wake=lambda: self._tts.speak("Yes?"),
        )

        host_port = self._config.get("host_port", 8765)
        ws_ip = "127.0.0.1" if self._role == "host" else self._config.get("host_ip", "127.0.0.1")
        self._network = NetworkClient(ws_ip, host_port)

        self._tuya = None
        self._spotify = None
        self._scheduler = None
        self._ai_clients: dict[str, dict] = {}
        self._unit_locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()
        self._system_prompt = None

        if self._role == "host":
            action_log.configure()
            t = threading.Thread(
                target=run_server,
                kwargs={"host": "0.0.0.0", "port": host_port},
                daemon=True,
            )
            t.start()
            print(f"[Compressor] Host server started on port {host_port}")
            time.sleep(1)  # Give uvicorn time to bind before the WS client connects

            location = self._network.get_info()

            tuya_cfg = self._config.get("tuya", {})
            devices = tuya_cfg.get("devices", [])
            self._tuya = TuyaController(devices)

            spotify_cfg = self._config.get("spotify", {})
            self._spotify = (
                SpotifyController(
                    spotify_cfg["client_id"],
                    spotify_cfg["client_secret"],
                    spotify_cfg["redirect_uri"],
                )
                if spotify_cfg
                else None
            )

            self._system_prompt = build_system_prompt(location, devices)

            self._scheduler = Scheduler()
            self._scheduler.register(
                "tuya_sync",
                lambda: tuya_sync.run(on_complete=self._on_tuya_sync),
                hour=0,  # midnight
            )
            self._scheduler.start()

            # Only wire the query handler once all host state above is fully
            # constructed. Until this line, app.state.query_handler stays at
            # its module-level default (None), so host_server.py's own
            # "Host is not ready to process queries yet." response covers
            # the startup window instead of _process_query touching
            # partially-initialized state.
            app.state.query_handler = self._process_query

        # WebSocket for house-speaker coordination
        self._network.on_message(self._handle_network_command)
        self._network.start_websocket()

    def _on_tuya_sync(self, updated_devices: list[dict]) -> None:
        """Reload TuyaController after a successful cloud sync."""
        self._tuya = TuyaController(updated_devices)
        log.info("[Assistant] TuyaController reloaded with %d device(s).", len(updated_devices))

    def _handle_network_command(self, payload: dict):
        """Handle commands broadcast from other devices (e.g. house-speaker sync)."""
        if payload.get("type") == "spotify" and self._spotify:
            self._spotify.control(
                payload["action"],
                payload.get("query"),
                house_speakers=False,
            )

    def _get_unit_lock(self, unit_name: str) -> threading.Lock:
        """Return (creating if needed) the lock that serializes requests for one unit.

        Different units can still run concurrently — a single unit just can't
        have two conversations in flight at once, which is correct anyway
        since they'd share (and corrupt) the same AIClient's message history.
        """
        with self._registry_lock:
            lock = self._unit_locks.get(unit_name)
            if lock is None:
                lock = threading.Lock()
                self._unit_locks[unit_name] = lock
            return lock

    def _get_ai_client(self, unit_name: str) -> AIClient:
        """Return a per-unit AIClient so different units' conversations never mix.

        Must be called while holding that unit's lock (see _get_unit_lock) —
        callers are _process_query and _reset_conversation, both of which do.
        """
        now = time.time()
        entry = self._ai_clients.get(unit_name)
        if entry is None:
            client = AIClient(self._config["anthropic_api_key"], self._system_prompt)
            self._ai_clients[unit_name] = {"client": client, "last_active": now}
            return client
        if now - entry["last_active"] > IDLE_RESET_SECONDS:
            entry["client"].reset()
        entry["last_active"] = now
        return entry["client"]

    def _reset_conversation(self, unit_name: str) -> None:
        with self._get_unit_lock(unit_name):
            entry = self._ai_clients.get(unit_name)
            if entry:
                entry["client"].reset()

    def _process_query(self, unit_name: str, text: str) -> str:
        """Handle one query end-to-end. Used for both local (host) and remote (follower) requests."""
        with self._get_unit_lock(unit_name):
            action_log.log_query(unit_name, text)
            ai = self._get_ai_client(unit_name)
            handler = lambda tool_name, tool_input: self._tool_handler(unit_name, tool_name, tool_input)
            try:
                response = ai.ask(text, handler)
            except Exception as e:
                print(f"[Error] {e}")
                action_log.log_error(unit_name, "ai_ask", str(e))
                return "Sorry, something went wrong."
            action_log.log_response(unit_name, response)
            return response

    def _tool_handler(self, unit_name: str, tool_name: str, tool_input: dict) -> str:
        print(f"[Tool] {tool_name} called with: {tool_input}")
        if tool_name == "control_tuya_device":
            result = self._tuya.control(tool_input["device_name"], tool_input["action"])
            print(f"[Tool] control_tuya_device result: {result}")
            action_log.log_tool_call(unit_name, tool_name, tool_input, result)
            return result

        if tool_name == "control_spotify" and self._spotify:
            house = tool_input.get("house_speakers", False)
            result = self._spotify.control(
                tool_input["action"],
                tool_input.get("query"),
                house_speakers=house,
            )
            print(f"[Tool] control_spotify result: {result}")
            action_log.log_tool_call(unit_name, tool_name, tool_input, result)
            if house:
                self._network.broadcast({
                    "type": "spotify",
                    "action": tool_input["action"],
                    "query": tool_input.get("query"),
                })
            return result

        print(f"[Tool] Unknown or unconfigured tool: {tool_name}")
        return "Integration not configured."

    def run(self):
        try:
            self._tts.speak("Compressor ready.")
        except Exception as e:
            print(f"[TTS Error] {e}")
        try:
            for initial_query in self._listener.listen_for_commands():
                query = initial_query
                while query:
                    print(f"[Assistant] Query received: '{query}'")
                    try:
                        self._tts.speak("On it.")
                    except Exception as e:
                        print(f"[TTS Error] {e}")
                    print("[Assistant] Processing query...")
                    if self._role == "host":
                        response = self._process_query(self._unit_name, query)
                    else:
                        response = self._network.query(self._unit_name, query)
                    print(f"[Assistant] Response: '{response[:80]}'")
                    print("[Assistant] Speaking response...")
                    try:
                        self._tts.speak(response)
                    except Exception as e:
                        print(f"[TTS Error] {e}")
                    print("[Assistant] Done.")
                    query = self._listener.listen_once(timeout=5)
                if self._role == "host":
                    self._reset_conversation(self._unit_name)
                print(f"[Compressor] Listening for wake word '{self._listener.wake_word}'...")
        except KeyboardInterrupt:
            print("\n[Compressor] Shutting down.")
