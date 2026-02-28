# Condensor Home Assistant - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python voice assistant named "Condensor" that wakes on the keyword "Condensor", answers questions via the Claude API, controls Tuya IoT devices, integrates with Spotify, and coordinates across a home network with a Host/Client architecture.

**Architecture:**
- A continuous microphone loop detects the wake word "Condensor" via Google Speech Recognition; the trailing query is sent to the Claude API which uses tool-use to decide between a plain text answer, a Tuya device command, or a Spotify command.
- The desktop (Host) runs a FastAPI server that exposes shared location info (via IP geolocation) and a WebSocket hub so all connected clients can coordinate "house speaker" Spotify playback.
- Both desktop and laptop run the same codebase; `role: host` vs `role: client` in `config.yaml` determines behavior at startup.

**Tech Stack:** Python 3.10+, `anthropic`, `SpeechRecognition`, `pyaudio`, `pyttsx3`, `tinytuya`, `spotipy`, `fastapi`, `uvicorn`, `httpx`, `websockets`, `pyyaml`, `pytest`, `pytest-mock`

---

## Project File Structure

```
compressor/
├── main.py
├── config.yaml                  (created by user from config.example.yaml)
├── config.example.yaml
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── assistant.py             # main orchestration loop
│   ├── stt.py                   # speech-to-text + wake word
│   ├── tts.py                   # text-to-speech
│   ├── ai_client.py             # Claude API + tool-use routing
│   ├── config_loader.py         # load + validate config.yaml
│   ├── network/
│   │   ├── __init__.py
│   │   ├── host_server.py       # FastAPI server (Host only)
│   │   └── client.py            # HTTP + WebSocket client
│   └── integrations/
│       ├── __init__.py
│       ├── tuya.py              # Tuya IoT device control
│       └── spotify.py           # Spotify playback control
└── tests/
    ├── __init__.py
    ├── test_config_loader.py
    ├── test_stt.py
    ├── test_tts.py
    ├── test_ai_client.py
    ├── test_tuya.py
    ├── test_spotify.py
    └── test_network.py
```

---

## External Accounts / Keys Required (read before starting)

| Service | What you need | Where to get it |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | console.anthropic.com |
| Tuya IoT | Client ID, Client Secret, device IDs, local keys | iot.tuya.com – create a project, then use `tinytuya wizard` to scan local devices |
| Spotify | Client ID, Client Secret | developer.spotify.com – create an app, set redirect URI to `http://localhost:8888/callback` |

> Tuya local keys: run `python -m tinytuya wizard` after setting up the IoT project. It will scan your LAN and write device info to `devices.json`. Copy the `id`, `key`, and `ip` for each device into `config.yaml`.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config.example.yaml`
- Create: `src/__init__.py`, `src/network/__init__.py`, `src/integrations/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Create `requirements.txt`**

```
anthropic>=0.40.0
SpeechRecognition>=3.10.0
pyaudio>=0.2.14
pyttsx3>=2.90
tinytuya>=1.14.0
spotipy>=2.24.0
fastapi>=0.115.0
uvicorn>=0.32.0
httpx>=0.27.0
websockets>=13.0
pyyaml>=6.0
pytest>=8.0
pytest-mock>=3.14
pytest-asyncio>=0.24
```

**Step 2: Create `config.example.yaml`**

```yaml
# Role of this machine: "host" (desktop) or "client" (laptop)
role: host

# Wake word spoken to activate the assistant
wake_word: condensor

# Only required when role is "client" — the Host machine's LAN IP
host_ip: 192.168.1.100
host_port: 8765

# Anthropic API key (https://console.anthropic.com)
anthropic_api_key: YOUR_ANTHROPIC_API_KEY_HERE

# Tuya IoT devices
# Run `python -m tinytuya wizard` to discover devices and get their keys
tuya:
  devices:
    - name: Living Room Light
      device_id: abc123def456
      local_key: xxxxxxxxxxxx
      ip: 192.168.1.50
      version: 3.3
    - name: Bedroom Fan
      device_id: def789ghi012
      local_key: yyyyyyyyyyyy
      ip: 192.168.1.51
      version: 3.3

# Spotify (https://developer.spotify.com — create an app)
spotify:
  client_id: YOUR_SPOTIFY_CLIENT_ID
  client_secret: YOUR_SPOTIFY_CLIENT_SECRET
  redirect_uri: http://localhost:8888/callback
```

**Step 3: Create empty `__init__.py` files**

```bash
touch src/__init__.py src/network/__init__.py src/integrations/__init__.py tests/__init__.py
```

**Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

> **Windows note:** If `pip install pyaudio` fails, run:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```
---

## Task 2: Config Loader

**Files:**
- Create: `src/config_loader.py`
- Create: `tests/test_config_loader.py`

**Step 1: Write the failing tests**

```python
# tests/test_config_loader.py
import pytest
from pathlib import Path


def write_config(tmp_path, content: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return str(p)


def test_load_config_returns_dict(tmp_path):
    path = write_config(tmp_path, "role: host\nwake_word: condensor\nanthropic_api_key: key123\n")
    from src.config_loader import load_config
    result = load_config(path)
    assert result["role"] == "host"
    assert result["wake_word"] == "condensor"


def test_load_config_missing_required_key_raises(tmp_path):
    path = write_config(tmp_path, "role: host\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="wake_word"):
        load_config(path)


def test_load_config_file_not_found():
    from src.config_loader import load_config
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")


def test_load_config_client_requires_host_ip(tmp_path):
    path = write_config(tmp_path, "role: client\nwake_word: condensor\nanthropic_api_key: key\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="host_ip"):
        load_config(path)
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_config_loader.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `config_loader` doesn't exist yet.

**Step 3: Implement `src/config_loader.py`**

```python
# src/config_loader.py
import yaml

REQUIRED_KEYS = ["role", "wake_word", "anthropic_api_key"]


class ConfigError(Exception):
    pass


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)

    for key in REQUIRED_KEYS:
        if key not in config:
            raise ConfigError(f"Missing required config key: '{key}'")

    if config["role"] == "client" and "host_ip" not in config:
        raise ConfigError("Clients must specify 'host_ip' in config")

    return config
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config_loader.py -v
```

Expected: 4 passed.

---

## Task 3: Text-to-Speech (TTS) Module

**Files:**
- Create: `src/tts.py`
- Create: `tests/test_tts.py`

**Step 1: Write the failing tests**

```python
# tests/test_tts.py
def test_speak_invokes_engine(mocker):
    mock_init = mocker.patch("src.tts.pyttsx3.init")
    mock_engine = mock_init.return_value

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("hello world")

    mock_engine.say.assert_called_once_with("hello world")
    mock_engine.runAndWait.assert_called_once()


def test_speak_empty_string_does_nothing(mocker):
    mock_init = mocker.patch("src.tts.pyttsx3.init")
    mock_engine = mock_init.return_value

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("")

    mock_engine.say.assert_not_called()
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_tts.py -v
```

**Step 3: Implement `src/tts.py`**

```python
# src/tts.py
import pyttsx3


class TTSEngine:
    def __init__(self, rate: int = 175):
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", rate)

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        self._engine.say(text)
        self._engine.runAndWait()
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_tts.py -v
```

Expected: 2 passed.

---

## Task 4: Speech-to-Text + Wake Word Detection

**Files:**
- Create: `src/stt.py`
- Create: `tests/test_stt.py`

**Step 1: Write the failing tests**

```python
# tests/test_stt.py
def test_extract_query_finds_keyword():
    from src.stt import extract_query
    result = extract_query("condensor tell me about mars", "condensor")
    assert result == "tell me about mars"


def test_extract_query_case_insensitive():
    from src.stt import extract_query
    result = extract_query("Condensor How far is Chicago", "condensor")
    assert result == "how far is chicago"


def test_extract_query_returns_none_when_missing():
    from src.stt import extract_query
    result = extract_query("tell me about mars", "condensor")
    assert result is None


def test_extract_query_returns_none_when_nothing_after_keyword():
    from src.stt import extract_query
    result = extract_query("condensor", "condensor")
    assert result is None


def test_speech_listener_yields_query(mocker):
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mock_mic = mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.side_effect = [
        "hello there",           # not a wake word — skip
        "condensor play music",  # wake word — yield query
        StopIteration,
    ]

    from src.stt import SpeechListener
    listener = SpeechListener("condensor")
    gen = listener.listen_for_commands()
    result = next(gen)
    assert result == "play music"
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_stt.py -v
```

**Step 3: Implement `src/stt.py`**

```python
# src/stt.py
from typing import Optional, Iterator
import speech_recognition as sr


def extract_query(text: str, wake_word: str) -> Optional[str]:
    lower = text.lower()
    if wake_word not in lower:
        return None
    idx = lower.index(wake_word) + len(wake_word)
    query = lower[idx:].strip()
    return query if query else None


class SpeechListener:
    def __init__(self, wake_word: str):
        self.wake_word = wake_word.lower()
        self._recognizer = sr.Recognizer()

    def listen_for_commands(self) -> Iterator[str]:
        with sr.Microphone() as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)
            print(f"[Condensor] Listening for wake word '{self.wake_word}'...")
            while True:
                try:
                    audio = self._recognizer.listen(source, timeout=1, phrase_time_limit=10)
                    text = self._recognizer.recognize_google(audio)
                    query = extract_query(text, self.wake_word)
                    if query:
                        print(f"[Condensor] Heard: {query}")
                        yield query
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as e:
                    print(f"[STT Error] {e}")
                    continue
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_stt.py -v
```

Expected: 5 passed.

---

## Task 5: Claude API Client with Tool-Use

This is the brain of the assistant. Claude receives the query plus two tools (`control_tuya_device`, `control_spotify`). If Claude calls a tool, the result is fed back and Claude produces a final spoken response.

**Files:**
- Create: `src/ai_client.py`
- Create: `tests/test_ai_client.py`

**Step 1: Write the failing tests**

```python
# tests/test_ai_client.py
import pytest


def make_text_response(mocker, text: str):
    """Helper: mock a terminal Claude response with plain text."""
    block = mocker.Mock()
    block.type = "text"
    block.text = text
    response = mocker.Mock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def make_tool_response(mocker, tool_name: str, tool_input: dict, tool_id: str = "toolu_01"):
    """Helper: mock a Claude response that calls a tool."""
    block = mocker.Mock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = mocker.Mock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def test_ask_returns_text_on_plain_answer(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.return_value = make_text_response(mocker, "The universe is vast.")

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("Tell me about space", lambda name, inp: "ok")

    assert result == "The universe is vast."


def test_ask_calls_tool_then_returns_text(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.side_effect = [
        make_tool_response(mocker, "control_tuya_device", {"device_name": "Living Room Light", "action": "on"}),
        make_text_response(mocker, "Living room light turned on."),
    ]

    tool_calls = []

    def handler(name, inp):
        tool_calls.append((name, inp))
        return "Living Room Light turned on"

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("turn on the living room light", handler)

    assert len(tool_calls) == 1
    assert tool_calls[0][0] == "control_tuya_device"
    assert result == "Living room light turned on."


def test_ask_returns_fallback_on_empty_content(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    response = mocker.Mock()
    response.stop_reason = "end_turn"
    response.content = []
    mock_create.return_value = response

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("hello", lambda name, inp: "")

    assert result == "I couldn't generate a response."
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_ai_client.py -v
```

**Step 3: Implement `src/ai_client.py`**

```python
# src/ai_client.py
from typing import Callable
import anthropic

TOOLS = [
    {
        "name": "control_tuya_device",
        "description": "Turn a registered smart home IoT device on, off, or toggle its state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Human-readable name of the device, e.g. 'Living Room Light'"
                },
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "toggle"],
                    "description": "Action to perform"
                }
            },
            "required": ["device_name", "action"]
        }
    },
    {
        "name": "control_spotify",
        "description": "Control Spotify music playback. Use house_speakers=true when the user says 'house speakers' or wants music everywhere.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "volume_up", "volume_down"],
                    "description": "Playback action"
                },
                "query": {
                    "type": "string",
                    "description": "Search term for the 'play' action, e.g. 'jazz', 'Radiohead', 'chill playlist'"
                },
                "house_speakers": {
                    "type": "boolean",
                    "description": "If true, play on all connected devices in the house"
                }
            },
            "required": ["action"]
        }
    }
]


class AIClient:
    def __init__(self, api_key: str, system_prompt: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._system = system_prompt

    def ask(self, query: str, tool_handler: Callable[[str, dict], str]) -> str:
        messages = [{"role": "user", "content": query}]

        while True:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self._system,
                tools=TOOLS,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = tool_handler(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "I couldn't generate a response."
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_ai_client.py -v
```

Expected: 3 passed.

---

## Task 6: Tuya Integration

**Files:**
- Create: `src/integrations/tuya.py`
- Create: `tests/test_tuya.py`

**Step 1: Write the failing tests**

```python
# tests/test_tuya.py
import pytest

DEVICES = [
    {"name": "Living Room Light", "device_id": "abc", "local_key": "xxx", "ip": "192.168.1.50", "version": 3.3},
    {"name": "Bedroom Fan", "device_id": "def", "local_key": "yyy", "ip": "192.168.1.51", "version": 3.3},
]


def test_turn_on_device(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Living Room Light", "on")

    mock_inst.turn_on.assert_called_once()
    assert "on" in result.lower()


def test_turn_off_device(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Bedroom Fan", "off")

    mock_inst.turn_off.assert_called_once()
    assert "off" in result.lower()


def test_unknown_device_returns_error(mocker):
    mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Nonexistent Device", "on")

    assert "not found" in result.lower()


def test_fuzzy_device_match(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    # "living room" is a substring of "Living Room Light"
    result = ctrl.control("living room", "on")

    mock_inst.turn_on.assert_called_once()
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_tuya.py -v
```

**Step 3: Implement `src/integrations/tuya.py`**

```python
# src/integrations/tuya.py
import tinytuya


class TuyaController:
    def __init__(self, devices: list[dict]):
        # devices: list of {name, device_id, local_key, ip, version}
        self._devices = {d["name"].lower(): d for d in devices}

    def _find_device(self, name: str) -> dict | None:
        key = name.lower()
        if key in self._devices:
            return self._devices[key]
        # Fuzzy: check if query is substring of any device name (or vice versa)
        for dev_key, dev in self._devices.items():
            if key in dev_key or dev_key in key:
                return dev
        return None

    def control(self, device_name: str, action: str) -> str:
        dev = self._find_device(device_name)
        if dev is None:
            return f"Device '{device_name}' not found. Check your config.yaml device list."

        device = tinytuya.OutletDevice(
            dev_id=dev["device_id"],
            address=dev["ip"],
            local_key=dev["local_key"],
            version=dev.get("version", 3.3),
        )

        if action == "on":
            device.turn_on()
        elif action == "off":
            device.turn_off()
        elif action == "toggle":
            status = device.status()
            is_on = status.get("dps", {}).get("1", False)
            device.turn_off() if is_on else device.turn_on()

        return f"{dev['name']} turned {action}."
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_tuya.py -v
```

Expected: 4 passed.


---

## Task 7: Spotify Integration

**Files:**
- Create: `src/integrations/spotify.py`
- Create: `tests/test_spotify.py`

**Step 1: Write the failing tests**

```python
# tests/test_spotify.py
import pytest


def make_controller(mocker):
    mocker.patch("src.integrations.spotify.SpotifyOAuth")
    mock_sp_cls = mocker.patch("src.integrations.spotify.spotipy.Spotify")
    mock_sp = mock_sp_cls.return_value
    from src.integrations.spotify import SpotifyController
    ctrl = SpotifyController("cid", "csecret", "http://localhost:8888/callback")
    return ctrl, mock_sp


def test_pause(mocker):
    ctrl, mock_sp = make_controller(mocker)
    result = ctrl.control("pause")
    mock_sp.pause_playback.assert_called_once()
    assert "paused" in result.lower()


def test_next_track(mocker):
    ctrl, mock_sp = make_controller(mocker)
    result = ctrl.control("next")
    mock_sp.next_track.assert_called_once()
    assert "next" in result.lower()


def test_play_searches_and_starts(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": [{"id": "dev1", "is_active": True}]}
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:123", "name": "Kind of Blue", "artists": [{"name": "Miles Davis"}]}]}
    }
    result = ctrl.control("play", query="miles davis kind of blue")
    mock_sp.start_playback.assert_called_once()
    assert "Kind of Blue" in result


def test_play_on_house_speakers_starts_on_all_devices(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {
        "devices": [
            {"id": "dev1", "is_active": True},
            {"id": "dev2", "is_active": False},
        ]
    }
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:abc", "name": "Song", "artists": [{"name": "Artist"}]}]}
    }
    ctrl.control("play", query="jazz", house_speakers=True)
    assert mock_sp.start_playback.call_count == 2


def test_no_devices_returns_message(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": []}
    result = ctrl.control("play", query="jazz")
    assert "no" in result.lower() and "device" in result.lower()
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_spotify.py -v
```

**Step 3: Implement `src/integrations/spotify.py`**

```python
# src/integrations/spotify.py
import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)


class SpotifyController:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self._sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=SCOPE,
                open_browser=True,
            )
        )

    def _get_device_ids(self, house_speakers: bool) -> list[str]:
        devices = self._sp.devices().get("devices", [])
        if not devices:
            return []
        if house_speakers:
            return [d["id"] for d in devices]
        active = [d for d in devices if d["is_active"]]
        return [active[0]["id"]] if active else [devices[0]["id"]]

    def control(self, action: str, query: str = None, house_speakers: bool = False) -> str:
        if action == "pause":
            self._sp.pause_playback()
            return "Playback paused."

        if action == "next":
            self._sp.next_track()
            return "Skipped to next track."

        if action == "previous":
            self._sp.previous_track()
            return "Playing previous track."

        if action == "volume_up":
            current = self._sp.current_playback()
            vol = min(100, current["device"]["volume_percent"] + 10)
            self._sp.volume(vol)
            return f"Volume at {vol}%."

        if action == "volume_down":
            current = self._sp.current_playback()
            vol = max(0, current["device"]["volume_percent"] - 10)
            self._sp.volume(vol)
            return f"Volume at {vol}%."

        if action == "play":
            device_ids = self._get_device_ids(house_speakers)
            if not device_ids:
                return "No Spotify devices found. Make sure Spotify is open on at least one device."

            if query:
                results = self._sp.search(q=query, limit=1, type="track")
                tracks = results.get("tracks", {}).get("items", [])
                if not tracks:
                    return f"No results found for '{query}'."
                track = tracks[0]
                uri = track["uri"]
                name = track["name"]
                artist = track["artists"][0]["name"]
                for did in device_ids:
                    self._sp.start_playback(device_id=did, uris=[uri])
                speaker_msg = " on all house speakers" if house_speakers else ""
                return f"Playing {name} by {artist}{speaker_msg}."
            else:
                for did in device_ids:
                    self._sp.start_playback(device_id=did)
                return "Resuming playback."

        return "Unknown Spotify command."
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_spotify.py -v
```

Expected: 5 passed.

---

## Task 8: Host Server (FastAPI + WebSocket hub)

The Host exposes two endpoints:
- `GET /info` — returns location data (city, region, timezone) via IP geolocation
- `WebSocket /ws` — clients connect here; any message received is broadcast to all other connected clients (used for house-speaker coordination)

**Files:**
- Create: `src/network/host_server.py`
- Create: `tests/test_network.py` (partial — server tests)

**Step 1: Write the failing tests**

```python
# tests/test_network.py
import pytest
from fastapi.testclient import TestClient


def test_info_endpoint_returns_location_keys(mocker):
    mocker.patch(
        "src.network.host_server.get_location",
        return_value={"city": "Chicago", "region": "Illinois", "country": "US", "timezone": "America/Chicago"}
    )
    from src.network.host_server import app
    client = TestClient(app)
    resp = client.get("/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "Chicago"
    assert data["timezone"] == "America/Chicago"


def test_info_endpoint_handles_geolocation_failure(mocker):
    mocker.patch(
        "src.network.host_server.get_location",
        side_effect=Exception("network error")
    )
    from src.network.host_server import app
    client = TestClient(app)
    resp = client.get("/info")
    assert resp.status_code == 200
    assert resp.json()["city"] == "Unknown"
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_network.py -v
```

**Step 3: Implement `src/network/host_server.py`**

```python
# src/network/host_server.py
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
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_network.py -v
```

Expected: 2 passed.


---

## Task 9: Network Client Module

**Files:**
- Modify: `tests/test_network.py` (add client tests)
- Create: `src/network/client.py`

**Step 1: Add client tests to `tests/test_network.py`**

Append to the existing test file:

```python
def test_network_client_get_info(mocker):
    mock_get = mocker.patch("src.network.client.httpx.get")
    mock_get.return_value.json.return_value = {
        "city": "Chicago", "region": "Illinois", "country": "US", "timezone": "America/Chicago"
    }
    mock_get.return_value.raise_for_status = lambda: None

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    info = client.get_info()

    assert info["city"] == "Chicago"


def test_network_client_get_info_on_failure(mocker):
    mocker.patch("src.network.client.httpx.get", side_effect=Exception("timeout"))

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    info = client.get_info()

    assert info == {}
```

**Step 2: Run to confirm new tests fail**

```bash
pytest tests/test_network.py -v
```

**Step 3: Implement `src/network/client.py`**

```python
# src/network/client.py
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
```

**Step 4: Run all network tests**

```bash
pytest tests/test_network.py -v
```

Expected: 4 passed.


---

## Task 10: Main Assistant Loop

This wires all modules together. The `Assistant` class:
1. Loads config
2. If Host: starts the FastAPI server in a background thread
3. Connects to Host (or self) to get location info
4. Builds a system prompt for Claude
5. Listens for the wake word and routes queries through the AI client

**Files:**
- Create: `src/assistant.py`
- Create: `main.py`

**Step 1: Write the failing test**

```python
# tests/test_assistant.py
import pytest


def test_build_system_prompt_includes_location_and_devices():
    from src.assistant import build_system_prompt
    prompt = build_system_prompt(
        {"city": "Chicago", "region": "Illinois", "timezone": "America/Chicago"},
        [{"name": "Living Room Light"}, {"name": "Bedroom Fan"}]
    )
    assert "Chicago" in prompt
    assert "Living Room Light" in prompt
    assert "Bedroom Fan" in prompt
```

**Step 2: Run to confirm it fails**

```bash
pytest tests/test_assistant.py -v
```

**Step 3: Implement `src/assistant.py`**

```python
# src/assistant.py
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
                house_speakers=False,  # this device is already syncing
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
                # Broadcast to all connected devices
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
```

**Step 4: Create `main.py`**

```python
# main.py
from src.assistant import Assistant

if __name__ == "__main__":
    assistant = Assistant()
    assistant.run()
```

**Step 5: Run tests**

```bash
pytest tests/test_assistant.py -v
```

Expected: 1 passed.

**Step 6: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass.

---

## Task 11: End-to-End Smoke Test (Manual)

This is a manual verification step — not automated — because it requires physical hardware.

**Step 1: Copy and fill in the config**

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:
- Set `role: host` on the desktop
- Fill in `anthropic_api_key`
- Fill in Tuya device info (run `python -m tinytuya wizard` to discover devices)
- Fill in Spotify credentials (first run will open a browser to authorize)

**Step 2: Run on the desktop (Host)**

```bash
python main.py
```

You should hear: "Condensor ready."

**Step 3: Test each feature**

| Say | Expected behavior |
|---|---|
| "Condensor, how far is it from here to Chicago?" | Claude answers with distance based on your location |
| "Condensor, tell me about outer space." | Claude gives a brief spoken answer |
| "Condensor, how long should I boil broccoli for?" | Claude answers |
| "Condensor, turn on the living room light." | Tuya device activates; Claude confirms |
| "Condensor, play some jazz." | Spotify plays jazz on active device |
| "Condensor, play jazz on the house speakers." | Spotify plays on all devices |
| "Condensor, pause the music." | Spotify pauses |

**Step 4: Set up the laptop (Client)**

On the laptop:
```bash
cp config.example.yaml config.yaml
```

Set `role: client` and `host_ip: <desktop-LAN-IP>` in config.yaml. Run:

```bash
python main.py
```

The laptop will now pull location from the desktop Host and coordinate on house-speaker commands.

**Step 5: Final commit**

```bash
git add config.example.yaml
git commit -m "docs: finalize config example with all integration fields"
```

---

## Troubleshooting Reference

| Issue | Fix |
|---|---|
| `pyaudio` install fails on Windows | `pip install pipwin && pipwin install pyaudio` |
| Google Speech Recognition fails | Check internet connection; it calls Google's free API |
| Tuya device not responding | Run `python -m tinytuya wizard` to refresh device IPs/keys |
| Spotify auth loop | Delete `.cache` file in project root and re-authenticate |
| Host server unreachable from laptop | Check Windows Firewall — allow port 8765 inbound |
| TTS voice sounds robotic | Change voice via `pyttsx3` properties; list available voices with `engine.getProperty('voices')` |
