import json
import logging
import threading
import time

from src.config_loader import load_config
from src.stt import SpeechListener
from src.tts import TTSEngine
from src.ai_client import AIClient
from src.integrations.tuya import TuyaController
from src.integrations.spotify import SpotifyController
from src.network.host_server import run_server
from src.network.client import NetworkClient
from src.scheduler import Scheduler
from src.tasks import tuya_sync

log = logging.getLogger(__name__)


def build_system_prompt(location: dict, devices: list[dict]) -> str:
    device_names = ", ".join(d["name"] for d in devices) if devices else "none"
    city = location.get("city", "Unknown")
    region = location.get("region", "Unknown")
    tz = location.get("timezone", "Unknown")
    return f"""You are Condensor, a friendly AI voice assistant for the home. Your responses will be spoken aloud, so:
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
        self._tts = TTSEngine()
        self._listener = SpeechListener(
            self._config["wake_word"],
            on_wake=lambda: self._tts.speak("Yes?"),
        )

        host_port = self._config.get("host_port", 8765)
        ws_ip = "127.0.0.1" if self._config.get("role") == "host" else self._config.get("host_ip", "127.0.0.1")
        self._network = NetworkClient(ws_ip, host_port)

        # Start server if this is the Host
        if self._config["role"] == "host":
            t = threading.Thread(
                target=run_server,
                kwargs={"host": "0.0.0.0", "port": host_port},
                daemon=True,
            )
            t.start()
            print(f"[Condensor] Host server started on port {host_port}")
            time.sleep(1)  # Give uvicorn time to bind before the WS client connects

        location = self._network.get_info()

        # Tuya
        tuya_cfg = self._config.get("tuya", {})
        devices = tuya_cfg.get("devices", [])
        self._tuya = TuyaController(devices)

        # Spotify
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

        # WebSocket for house-speaker coordination
        self._network.on_message(self._handle_network_command)
        self._network.start_websocket()

        system_prompt = build_system_prompt(location, devices)
        self._ai = AIClient(self._config["anthropic_api_key"], system_prompt)

        # Scheduled background tasks
        self._scheduler = Scheduler()
        self._scheduler.register(
            "tuya_sync",
            lambda: tuya_sync.run(on_complete=self._on_tuya_sync),
            hour=0,  # midnight
        )
        self._scheduler.start()

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

    def _tool_handler(self, tool_name: str, tool_input: dict) -> str:
        print(f"[Tool] {tool_name} called with: {tool_input}")
        if tool_name == "control_tuya_device":
            result = self._tuya.control(tool_input["device_name"], tool_input["action"])
            print(f"[Tool] control_tuya_device result: {result}")
            return result

        if tool_name == "control_spotify" and self._spotify:
            house = tool_input.get("house_speakers", False)
            result = self._spotify.control(
                tool_input["action"],
                tool_input.get("query"),
                house_speakers=house,
            )
            print(f"[Tool] control_spotify result: {result}")
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
            self._tts.speak("Condensor ready.")
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
                    print("[Assistant] Calling Claude...")
                    try:
                        response = self._ai.ask(query, self._tool_handler)
                        print(f"[Assistant] Claude responded: '{response[:80]}'")
                    except Exception as e:
                        print(f"[Error] {e}")
                        response = "Sorry, something went wrong."
                    print("[Assistant] Speaking response...")
                    try:
                        self._tts.speak(response)
                    except Exception as e:
                        print(f"[TTS Error] {e}")
                    print("[Assistant] Done.")
                    query = self._listener.listen_once(timeout=5)
                self._ai.reset()
                print(f"[Condensor] Listening for wake word '{self._listener.wake_word}'...")
        except KeyboardInterrupt:
            print("\n[Condensor] Shutting down.")
