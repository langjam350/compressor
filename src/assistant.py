import logging
import queue
import re
import threading
import time

from src import action_log
from src.config_loader import load_config
from src.stt import SpeechListener
from src.tts import TTSEngine
from src.ai_client import AIClient
from src.tools import TOOLS
from src.actions import ACTIONS
from src.actions.context import ActionContext
from src.integrations.tuya import TuyaController
from src.integrations.spotify import SpotifyController
from src.integrations.launcher import ProgramLauncher
from src.integrations.coding_agents import create_session
from src.network.host_server import app, run_server
from src.network.client import NetworkClient
from src.scheduler import Scheduler
from src.tasks import tuya_sync

log = logging.getLogger(__name__)

IDLE_RESET_SECONDS = 30
CLAUDE_MODE_LISTEN_CHUNK_SECONDS = 10  # short chunks so finished tasks get spoken promptly
CLAUDE_MODE_IDLE_EXIT_SECONDS = 900    # continuous inactivity before auto-exit
_CLAUDE_ENTRY_RE = re.compile(r"^\s*start\s+claude(?:\s+code)?(?:\s+in\s+(?P<name>.+?))?\s*$", re.IGNORECASE)


def build_system_prompt(location: dict, devices: list[dict], programs: list[dict] | None = None) -> str:
    device_names = ", ".join(d["name"] for d in devices) if devices else "none"
    city = location.get("city", "Unknown")
    region = location.get("region", "Unknown")
    tz = location.get("timezone", "Unknown")

    program_lines = []
    for p in programs or []:
        if not p.get("name"):
            continue
        aliases = f" (aliases: {', '.join(p['aliases'])})" if p.get("aliases") else ""
        process_names = ", ".join((p.get("processes") or {}).keys())
        processes = f" — known processes: {process_names}" if process_names else ""
        program_lines.append(f"- {p['name']}{aliases}{processes}")
    programs_section = "\n".join(program_lines) if program_lines else "none configured"

    return f"""You are Compressor, a friendly AI voice assistant for the home. Your responses will be spoken aloud, so:
- Be concise (1-3 sentences unless the user asks for detail)
- Avoid markdown, bullet points, or formatting
- Speak naturally

Current location: {city}, {region} (timezone: {tz})
Registered smart home devices: {device_names}
Programs that can be opened by voice (open_program tool):
{programs_section}

You can control smart home devices, music, and open programs on the computer, but you are also a general-purpose AI assistant. Answer any question the user asks — cooking, trivia, advice, facts, recommendations — just like a knowledgeable friend would. Only use tools when the user wants to control a device, play music, or open a program.
"""


class Assistant:
    def __init__(self, config_path: str = "config.yaml"):
        self._config = load_config(config_path)
        self._role = self._config["role"]
        self._unit_name = self._config.get("unit_name", "host")
        self._tts = TTSEngine()
        self._listener = SpeechListener(
            self._config["wake_word"],
            on_wake=self._on_wake,
            wake_model_path=self._config.get("wake_model_path", "models/compressor.onnx"),
            wake_threshold=float(self._config.get("wake_threshold", 0.5)),
        )

        host_port = self._config.get("host_port", 8765)
        ws_ip = "127.0.0.1" if self._role == "host" else self._config.get("host_ip", "127.0.0.1")
        self._network = NetworkClient(ws_ip, host_port)
        self._launcher = ProgramLauncher(
            self._config.get("programs", []) or [],
            unit_name=self._unit_name,
        )

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

            self._system_prompt = build_system_prompt(
                location, devices, self._config.get("programs", []) or []
            )

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

    def _on_wake(self) -> None:
        self._tts.speak("Yes?")
        if self._role == "host":
            action_log.log_wake(self._unit_name)

    def _on_tuya_sync(self, updated_devices: list[dict]) -> None:
        """Reload TuyaController after a successful cloud sync."""
        self._tuya = TuyaController(updated_devices)
        log.info("[Assistant] TuyaController reloaded with %d device(s).", len(updated_devices))

    def _handle_network_command(self, payload: dict):
        """Handle commands broadcast from other units over the host's WS relay."""
        ptype = payload.get("type")
        if ptype == "spotify" and self._spotify:
            self._spotify.control(
                payload["action"],
                payload.get("query"),
                house_speakers=False,
            )
        elif ptype == "open_program":
            if payload.get("target_unit") != self._unit_name:
                return  # addressed to a different unit
            result = self._launcher.open(
                payload.get("program", ""),
                process=payload.get("process"),
                argument=payload.get("argument"),
            )
            print(f"[Compressor] Remote open_program: {result}")

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
            client = AIClient(self._config["anthropic_api_key"], self._system_prompt, TOOLS)
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

    def _parse_claude_mode_entry(self, text: str) -> str | None:
        """Return '' for bare 'start claude', the project name for
        'start claude in <name>', or None if this isn't an entry phrase."""
        match = _CLAUDE_ENTRY_RE.match(text.strip().strip(".,!?"))
        if not match:
            return None
        return (match.group("name") or "").strip()

    def _speak_safe(self, text: str) -> None:
        """Same defensive pattern as run()'s TTS calls: a dead TTS subprocess
        must not kill the mode or mask session cleanup."""
        try:
            self._tts.speak(text)
        except Exception as e:
            print(f"[TTS Error] {e}")

    def _run_claude_mode(self, target_name: str) -> None:
        """Route speech into a coding-agent session until the wake word
        is spoken ALONE (the universal escape), or idle timeout.

        Tasks run on a background worker thread so the mic keeps listening
        while the agent works: follow-ups arriving mid-task are queued,
        finished responses are spoken as they complete, and exiting cancels
        any in-flight task (a cancelled task's empty response is discarded).

        Must never let an exception escape — a malformed coding_agent config
        (e.g. a factory TypeError from a bad max_turns value) degrades to a
        spoken error instead of killing the whole process."""
        cfg = self._config.get("coding_agent")
        if not isinstance(cfg, dict) or not cfg.get("default_workdir"):
            self._speak_safe("Claude mode isn't configured on this unit.")
            return

        workdir = cfg["default_workdir"]
        if target_name:
            workdirs = {k.lower(): v for k, v in (cfg.get("workdirs") or {}).items()}
            workdir = workdirs.get(target_name.lower())
            if workdir is None:
                self._speak_safe(f"I don't have a project called {target_name}.")
                return

        session = None
        worker = None
        pending: queue.Queue = queue.Queue()    # utterances awaiting the worker (None = shut down)
        results: queue.Queue = queue.Queue()    # (utterance, response) pairs ready to speak
        outstanding = 0                         # enqueued but not yet drained

        def _drain_results() -> int:
            """Speak and log every finished task; return how many were drained."""
            nonlocal outstanding
            drained = 0
            while True:
                try:
                    utterance, response = results.get_nowait()
                except queue.Empty:
                    return drained
                drained += 1
                outstanding -= 1
                if not response:
                    continue  # cancelled task — discard silently
                if self._role == "host":
                    action_log.log_claude_mode(self._unit_name, "exchange", f"{utterance} -> {response[:200]}")
                print(f"[Claude] {response}")
                self._speak_safe(response)

        def _worker_loop() -> None:
            while True:
                item = pending.get()
                if item is None:
                    return
                try:
                    response = session.send(item)
                except Exception as e:  # send() shouldn't raise, but a dead worker would strand the mode
                    response = f"Claude Code failed ({e})."
                results.put((item, response))

        try:
            try:
                session = create_session(cfg)
                session.start(workdir)
                worker = threading.Thread(target=_worker_loop, daemon=True, name="ClaudeModeWorker")
                worker.start()
                self._speak_safe("Starting Claude.")
                if self._role == "host":
                    action_log.log_claude_mode(self._unit_name, "enter", workdir)
                print(f"[Compressor] Claude mode: {workdir} — say '{self._listener.wake_word}' alone to exit.")

                idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
                while True:
                    if _drain_results():
                        idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
                    utterance = self._listener.listen_once(
                        timeout=CLAUDE_MODE_LISTEN_CHUNK_SECONDS, phrase_time_limit=30
                    )
                    if not utterance:
                        if outstanding > 0:
                            idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS  # running task = activity
                        elif time.time() >= idle_deadline:
                            self._speak_safe("Claude mode timed out.")
                            break
                        time.sleep(1)
                        continue
                    # Escape rule: wake word ALONE exits; embedded passes through.
                    if utterance.strip().strip(".,!?").lower() == self._listener.wake_word:
                        break
                    print(f"[Claude] > {utterance}")
                    self._speak_safe("Queued." if outstanding > 0 else "Working on it.")
                    pending.put(utterance)
                    outstanding += 1
                    idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
            except Exception as e:
                print(f"[Claude] mode error: {e}")
                self._speak_safe("Claude mode hit an error.")
        finally:
            cancel = getattr(session, "cancel", None)
            if callable(cancel):
                try:
                    cancel()  # kill any in-flight task; its send() returns "" fast
                except Exception as e:
                    print(f"[Claude] session cancel failed: {e}")
            pending.put(None)
            if worker is not None:
                worker.join(timeout=30)
            _drain_results()  # speak whatever finished but wasn't voiced yet
            if session is not None:
                try:
                    session.stop()
                except Exception as e:
                    print(f"[Claude] session stop failed: {e}")
            if self._role == "host":
                action_log.log_claude_mode(self._unit_name, "exit", workdir)
            self._speak_safe("Compressor ready.")

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
            entry = self._ai_clients.get(unit_name)
            if entry is not None:
                entry["last_active"] = time.time()
            action_log.log_response(unit_name, response)
            return response

    def _tool_handler(self, unit_name: str, tool_name: str, tool_input: dict) -> str:
        print(f"[Tool] {tool_name} called with: {tool_input}")
        action = ACTIONS.get(tool_name)
        if action is None:
            print(f"[Tool] Unknown or unconfigured tool: {tool_name}")
            return "Integration not configured."
        ctx = ActionContext(
            unit_name=unit_name,
            tuya=self._tuya,
            spotify=self._spotify,
            launcher=self._launcher,
            network=self._network,
            config=self._config,
            host_unit_name=self._unit_name,
        )
        result = action(ctx, tool_input)
        print(f"[Tool] {tool_name} result: {result}")
        action_log.log_tool_call(unit_name, tool_name, tool_input, result)
        return result

    def run(self):
        try:
            self._tts.speak("Compressor ready.")
        except Exception as e:
            print(f"[TTS Error] {e}")
        try:
            for initial_query in self._listener.listen_for_commands():
                query = initial_query
                while query:
                    claude_target = self._parse_claude_mode_entry(query)
                    if claude_target is not None:
                        self._run_claude_mode(claude_target)
                        break  # back to the wake-word loop in normal mode
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
