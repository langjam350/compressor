import json
import threading

from src.config_loader import load_config
from src.stt import SpeechListener
from src.tts import TTSEngine
from src.ai_client import AIClient
from src.integrations.tuya import TuyaController
from src.integrations.spotify import SpotifyController
from src.network.host_server import run_server
from src.network.client import NetworkClient


def build_system_prompt(location: dict, devices: list[dict]) -> str:
    device_names = ", ".join(d["name"] for d in devices) if devices else "none"
    city = location.get("city", "Unknown")
    region = location.get("region", "Unknown")
    tz = location.get("timezone", "Unknown")
    return f"""You are Condensor, a friendly home voice assistant. Your responses will be spoken aloud, so:
- Be concise (1-3 sentences unless the user asks for detail)
- Avoid markdown, bullet points, or formatting
- Speak naturally

Current location: {city}, {region} (timezone: {tz})
Registered smart home devices: {device_names}

When the user asks to control a device or play music, call the appropriate tool, then briefly confirm the action.
"""


class Assistant:
    def __init__(self, config_path: str = "config.yaml"):
        self._config = load_config(config_path)
        self._tts = TTSEngine()
        self._listener = SpeechListener(self._config["wake_word"])

        host_ip = self._config.get("host_ip", "127.0.0.1")
        host_port = self._config.get("host_port", 8765)
        self._network = NetworkClient(host_ip, host_port)

        # Start server if this is the Host
        if self._config["role"] == "host":
            t = threading.Thread(
                target=run_server,
                kwargs={"host": "0.0.0.0", "port": host_port},
                daemon=True,
            )
            t.start()
            print(f"[Condensor] Host server started on port {host_port}")

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

    def _handle_network_command(self, payload: dict):
        """Handle commands broadcast from other devices (e.g. house-speaker sync)."""
        if payload.get("type") == "spotify" and self._spotify:
            self._spotify.control(
                payload["action"],
                payload.get("query"),
                house_speakers=False,
            )

    def _tool_handler(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "control_tuya_device":
            return self._tuya.control(tool_input["device_name"], tool_input["action"])

        if tool_name == "control_spotify" and self._spotify:
            house = tool_input.get("house_speakers", False)
            result = self._spotify.control(
                tool_input["action"],
                tool_input.get("query"),
                house_speakers=house,
            )
            if house:
                self._network.broadcast({
                    "type": "spotify",
                    "action": tool_input["action"],
                    "query": tool_input.get("query"),
                })
            return result

        return "Integration not configured."

    def run(self):
        self._tts.speak("Condensor ready.")
        for query in self._listener.listen_for_commands():
            self._tts.speak("On it.")
            try:
                response = self._ai.ask(query, self._tool_handler)
            except Exception as e:
                print(f"[Error] {e}")
                response = "Sorry, something went wrong."
            self._tts.speak(response)
