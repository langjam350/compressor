# Voice-Driven Claude Code Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Start Claude" flips Compressor into a mode where speech routes into a persistent headless Claude Code session and responses are spoken back, until the wake word alone exits.

**Architecture:** A new agent-agnostic `src/integrations/coding_agents/` package (protocol + config-driven factory, Claude Code as the only v1 backend wrapping `claude -p --resume` one-shots). `Assistant.run()` gains deterministic phrase-match mode entry and a `_run_claude_mode()` loop: escape on bare wake word, forward everything else to `session.send()`, idle auto-exit.

**Tech Stack:** Python 3.11 (Windows), subprocess + shutil.which, pytest + pytest-mock. No new pip dependencies.

## Global Constraints

- The mode layer never references a vendor: it talks only to `create_session(cfg)` / `CodingAgentSession`. Which agent and model run comes from `config.yaml`'s `coding_agent:` section (`agent: claude_code`, optional `model:`).
- Only the Claude Code backend is implemented. No other backends — an unknown `agent:` value yields a stub session whose `send` returns `"Coding agent '<name>' isn't supported on this unit."`.
- Escape rule: the wake word ALONE (stripped of whitespace and trailing `.,!?`, lowercased, exactly equal) exits the mode. Embedded occurrences are forwarded verbatim to the session.
- Backend `send()` never raises — every failure (CLI missing, non-zero exit, JSON parse failure, timeout) returns a spoken-safe string.
- Never `--dangerously-skip-permissions`. Default `--permission-mode acceptEdits`, `--max-turns 25`, task timeout 600s, all config-overridable.
- Voice-sizing system prompt appended verbatim: `"Your final response will be spoken aloud through text-to-speech. Keep it under 3 sentences, plain prose, no markdown or code unless asked to read code."`
- Mode entry phrases: `start claude`, `start claude code`, optionally `... in <name>` (case-insensitive, full-utterance match).
- Constants: `CLAUDE_MODE_LISTEN_TIMEOUT = 300` (per listen_once call), `CLAUDE_MODE_IDLE_EXIT_SECONDS = 900` (silence auto-exit).
- Exiting always speaks `"Compressor ready."`.
- Never commit `config.yaml` (real secrets). Committed example config changes go only in `config.example.yaml`.
- Suite is currently 131 passing; must stay green after every task.

---

## File Structure

- Create: `src/integrations/coding_agents/__init__.py` — `CodingAgentSession` protocol, `_UnsupportedSession`, `create_session` factory.
- Create: `src/integrations/coding_agents/claude_code.py` — `ClaudeCodeSession` backend.
- Modify: `src/assistant.py` — constants, `_parse_claude_mode_entry`, `_run_claude_mode`, entry check in `run()`, import of `create_session`.
- Modify: `src/action_log.py` — `log_claude_mode`.
- Modify: `config.example.yaml`, local `config.yaml` (never staged), `README.md`.
- Create: `tests/test_coding_agents.py`. Modify: `tests/test_assistant.py`, `tests/test_action_log.py`.

---

### Task 1: Coding-agent package — protocol, factory, Claude Code backend

**Files:**
- Create: `src/integrations/coding_agents/__init__.py`
- Create: `src/integrations/coding_agents/claude_code.py`
- Create: `tests/test_coding_agents.py`

**Interfaces:**
- Consumes: nothing project-internal (stdlib only: subprocess, shutil, json).
- Produces: `create_session(agent_config: dict) -> CodingAgentSession`; sessions expose `start(workdir: str) -> None`, `send(text: str) -> str` (never raises), `stop() -> None`. `ClaudeCodeSession(model=None, permission_mode="acceptEdits", max_turns=25, task_timeout_seconds=600)`. Task 2 wires these into `Assistant`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_coding_agents.py`:

```python
import json
import subprocess


def _mock_run_result(mocker, result_text="Done.", session_id="sess-123", returncode=0, stderr=""):
    proc = mocker.Mock()
    proc.returncode = returncode
    proc.stdout = json.dumps({"result": result_text, "session_id": session_id})
    proc.stderr = stderr
    return proc


def _make_session(**kwargs):
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    session = ClaudeCodeSession(**kwargs)
    session.start("C:\\proj")
    return session


def test_factory_builds_claude_code_backend():
    from src.integrations.coding_agents import create_session
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    session = create_session({"agent": "claude_code", "model": "claude-sonnet-5",
                              "permission_mode": "plan", "max_turns": 10,
                              "task_timeout_seconds": 120})
    assert isinstance(session, ClaudeCodeSession)


def test_factory_defaults_agent_to_claude_code():
    from src.integrations.coding_agents import create_session
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    assert isinstance(create_session({}), ClaudeCodeSession)


def test_factory_unknown_agent_returns_stub_with_spoken_message():
    from src.integrations.coding_agents import create_session
    session = create_session({"agent": "gemini_cli"})
    session.start("C:\\proj")
    result = session.send("do something")
    assert result == "Coding agent 'gemini_cli' isn't supported on this unit."
    session.stop()  # must not raise


def test_send_builds_expected_first_command(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker))

    session = _make_session()
    result = session.send("add a button")

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "C:\\npm\\claude.cmd"
    assert cmd[1:3] == ["-p", "add a button"]
    assert "--resume" not in cmd
    assert "--model" not in cmd  # unset -> omitted
    assert ["--output-format", "json"] == cmd[cmd.index("--output-format"):cmd.index("--output-format") + 2]
    assert ["--permission-mode", "acceptEdits"] == cmd[cmd.index("--permission-mode"):cmd.index("--permission-mode") + 2]
    assert ["--add-dir", "C:\\proj"] == cmd[cmd.index("--add-dir"):cmd.index("--add-dir") + 2]
    assert ["--max-turns", "25"] == cmd[cmd.index("--max-turns"):cmd.index("--max-turns") + 2]
    assert "--append-system-prompt" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert mock_run.call_args.kwargs["cwd"] == "C:\\proj"
    assert mock_run.call_args.kwargs["timeout"] == 600
    assert result == "Done."


def test_second_send_resumes_captured_session_id(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker, session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.send("second")

    second_cmd = mock_run.call_args_list[1].args[0]
    idx = second_cmd.index("--resume")
    assert second_cmd[idx + 1] == "sess-abc"


def test_model_flag_present_only_when_configured(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker))

    session = _make_session(model="claude-sonnet-5")
    session.send("hello")

    cmd = mock_run.call_args.args[0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-sonnet-5"


def test_missing_cli_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which", return_value=None)
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run")

    session = _make_session()
    result = session.send("hello")

    mock_run.assert_not_called()
    assert result == "Claude Code isn't installed on this unit."


def test_timeout_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                 side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600))

    session = _make_session()
    assert session.send("hello") == "That task timed out."


def test_nonzero_exit_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                 return_value=_mock_run_result(mocker, returncode=1, stderr="boom"))

    session = _make_session()
    result = session.send("hello")

    assert "failed" in result.lower()
    # never raises, and doesn't leak a wall of stderr to TTS
    assert len(result) < 200


def test_bad_json_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    proc = mocker.Mock()
    proc.returncode = 0
    proc.stdout = "not json at all"
    proc.stderr = ""
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run", return_value=proc)

    session = _make_session()
    result = session.send("hello")

    assert "failed" in result.lower()


def test_stop_clears_session_so_next_send_starts_fresh(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker, session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.stop()
    session.start("C:\\proj")
    session.send("fresh start")

    assert "--resume" not in mock_run.call_args_list[1].args[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_coding_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.integrations.coding_agents'`

- [ ] **Step 3: Implement the package**

`src/integrations/coding_agents/__init__.py`:

```python
"""Agent-agnostic coding-agent sessions.

The voice mode talks only to the CodingAgentSession interface; which
agent (and model) actually runs comes from config.yaml's coding_agent
section. v1 ships exactly one backend: Claude Code.
"""
from typing import Protocol


class CodingAgentSession(Protocol):
    def start(self, workdir: str) -> None: ...
    def send(self, text: str) -> str: ...
    def stop(self) -> None: ...


class _UnsupportedSession:
    """Stub returned for agents that have no backend yet."""

    def __init__(self, agent_name: str):
        self._agent_name = agent_name

    def start(self, workdir: str) -> None:
        pass

    def send(self, text: str) -> str:
        return f"Coding agent '{self._agent_name}' isn't supported on this unit."

    def stop(self) -> None:
        pass


def create_session(agent_config: dict) -> CodingAgentSession:
    """Build a session for the configured agent. Parameters come from config, not code."""
    agent = (agent_config.get("agent") or "claude_code").lower()
    if agent == "claude_code":
        from src.integrations.coding_agents.claude_code import ClaudeCodeSession
        return ClaudeCodeSession(
            model=agent_config.get("model"),
            permission_mode=agent_config.get("permission_mode", "acceptEdits"),
            max_turns=int(agent_config.get("max_turns", 25)),
            task_timeout_seconds=int(agent_config.get("task_timeout_seconds", 600)),
        )
    return _UnsupportedSession(agent)
```

`src/integrations/coding_agents/claude_code.py`:

```python
import json
import shutil
import subprocess

VOICE_SYSTEM_PROMPT = (
    "Your final response will be spoken aloud through text-to-speech. "
    "Keep it under 3 sentences, plain prose, no markdown or code unless "
    "asked to read code."
)


class ClaudeCodeSession:
    """Headless Claude Code sessions via one-shot `claude -p` invocations.

    Continuity across utterances comes from --resume with the session id
    captured on the first call. send() never raises — every failure
    returns a spoken-safe string.
    """

    def __init__(
        self,
        model: str | None = None,
        permission_mode: str = "acceptEdits",
        max_turns: int = 25,
        task_timeout_seconds: int = 600,
    ):
        self._model = model
        self._permission_mode = permission_mode
        self._max_turns = max_turns
        self._timeout = task_timeout_seconds
        self._workdir: str | None = None
        self._session_id: str | None = None

    def start(self, workdir: str) -> None:
        self._workdir = workdir
        self._session_id = None

    def send(self, text: str) -> str:
        try:
            cli = shutil.which("claude")
            if cli is None:
                return "Claude Code isn't installed on this unit."
            cmd = [
                cli, "-p", text,
                "--output-format", "json",
                "--permission-mode", self._permission_mode,
                "--add-dir", self._workdir,
                "--max-turns", str(self._max_turns),
                "--append-system-prompt", VOICE_SYSTEM_PROMPT,
            ]
            if self._model:
                cmd += ["--model", self._model]
            if self._session_id:
                cmd += ["--resume", self._session_id]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self._workdir,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                snippet = (proc.stderr or "").strip().splitlines()
                detail = snippet[-1][:120] if snippet else f"exit code {proc.returncode}"
                return f"Claude Code failed ({detail})."
            data = json.loads(proc.stdout)
            self._session_id = data.get("session_id", self._session_id)
            result = data.get("result")
            return str(result) if result else "Claude finished but returned no text."
        except subprocess.TimeoutExpired:
            return "That task timed out."
        except Exception as e:
            return f"Claude Code failed ({e})."

    def stop(self) -> None:
        self._session_id = None
        self._workdir = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_coding_agents.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the full suite, then commit**

Run: `py -m pytest tests/ -v` — expected 142 passing (131 + 11).

```bash
git add src/integrations/coding_agents/ tests/test_coding_agents.py
git commit -m "Add agent-agnostic coding-agent sessions with Claude Code backend"
```

---

### Task 2: Claude mode in `Assistant` — entry parsing, mode loop, escape rule

**Files:**
- Modify: `src/assistant.py`
- Modify: `src/action_log.py`
- Modify: `tests/test_assistant.py` (append), `tests/test_action_log.py` (append)

**Interfaces:**
- Consumes: `create_session(cfg)` and the session contract (Task 1); existing `SpeechListener.listen_once`, `TTSEngine.speak`, `action_log._write`.
- Produces: `Assistant._parse_claude_mode_entry(text: str) -> str | None` (None = not an entry phrase; `""` = default workdir; otherwise the spoken project name); `Assistant._run_claude_mode(target_name: str) -> None`; `action_log.log_claude_mode(unit: str, event: str, detail: str) -> None`; constants `CLAUDE_MODE_LISTEN_TIMEOUT = 300`, `CLAUDE_MODE_IDLE_EXIT_SECONDS = 900`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_action_log.py`:

```python
def test_log_claude_mode_writes_expected_fields(tmp_path):
    from src import action_log
    log_path = tmp_path / "actions.txt"
    action_log.configure(str(log_path))
    action_log.log_claude_mode("host", "enter", "C:\\git\\jldesigns")

    record = json.loads(log_path.read_text().strip().splitlines()[0])
    assert record["event"] == "claude_mode"
    assert record["mode_event"] == "enter"
    assert record["detail"] == "C:\\git\\jldesigns"
```

Append to `tests/test_assistant.py`:

```python
# --- Claude mode ---

CODING_AGENT_CFG = {
    "agent": "claude_code",
    "default_workdir": "C:\\git\\compressor",
    "workdirs": {"jldesigns": "C:\\git\\jldesigns"},
}


def _make_claude_mode_assistant(mocker, listener_queries, listen_once_returns, coding_agent=True):
    """Host assistant with a mocked coding-agent session factory."""
    config = {
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    }
    if coding_agent:
        config["coding_agent"] = dict(CODING_AGENT_CFG)
    mocker.patch("src.assistant.load_config", return_value=config)
    mock_tts = mocker.MagicMock()
    mocker.patch("src.assistant.TTSEngine", return_value=mock_tts)
    mock_listener = mocker.MagicMock()
    mock_listener.wake_word = "compressor"
    mock_listener.listen_for_commands.return_value = iter(listener_queries)
    mock_listener.listen_once.side_effect = list(listen_once_returns)
    mocker.patch("src.assistant.SpeechListener", return_value=mock_listener)
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")

    mock_session = mocker.MagicMock()
    mock_session.send.return_value = "Task complete."
    mock_factory = mocker.patch("src.assistant.create_session", return_value=mock_session)

    from src.assistant import Assistant
    return Assistant(), mock_session, mock_factory, mock_tts


def test_parse_claude_mode_entry_variants(mocker):
    assistant, _, _, _ = _make_claude_mode_assistant(mocker, [], [])
    assert assistant._parse_claude_mode_entry("start claude") == ""
    assert assistant._parse_claude_mode_entry("Start Claude Code") == ""
    assert assistant._parse_claude_mode_entry("start claude in jldesigns") == "jldesigns"
    assert assistant._parse_claude_mode_entry("start claude code in my site") == "my site"
    assert assistant._parse_claude_mode_entry("restart claude") is None
    assert assistant._parse_claude_mode_entry("turn on the lights") is None


def test_start_claude_enters_mode_and_routes_speech_to_session(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["add a dark mode toggle", "compressor"],
    )
    assistant.run()

    mock_factory.assert_called_once()
    mock_session.start.assert_called_once_with("C:\\git\\compressor")
    mock_session.send.assert_called_once_with("add a dark mode toggle")
    mock_tts.speak.assert_any_call("Task complete.")


def test_wake_word_alone_exits_mode(mocker):
    assistant, mock_session, _, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["compressor"],
    )
    assistant.run()

    mock_session.send.assert_not_called()
    mock_session.stop.assert_called_once()
    mock_tts.speak.assert_any_call("Compressor ready.")


def test_wake_word_with_punctuation_still_exits(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["Compressor."],
    )
    assistant.run()

    mock_session.send.assert_not_called()
    mock_session.stop.assert_called_once()


def test_wake_word_embedded_in_sentence_is_forwarded_not_exit(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["add a test to compressor's launcher", "compressor"],
    )
    assistant.run()

    mock_session.send.assert_called_once_with("add a test to compressor's launcher")


def test_start_claude_in_named_project_uses_configured_workdir(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude in jldesigns"],
        listen_once_returns=["compressor"],
    )
    assistant.run()

    mock_session.start.assert_called_once_with("C:\\git\\jldesigns")


def test_start_claude_unknown_project_refuses_without_entering_mode(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude in narnia"],
        listen_once_returns=[],
    )
    assistant.run()

    mock_factory.assert_not_called()
    mock_session.start.assert_not_called()
    assert any("narnia" in str(c) for c in mock_tts.speak.call_args_list)


def test_start_claude_without_config_refuses(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=[],
        coding_agent=False,
    )
    assistant.run()

    mock_factory.assert_not_called()
    assert any("isn't configured" in str(c) for c in mock_tts.speak.call_args_list)


def test_mode_utterances_never_reach_normal_ai(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["what is 2 plus 2", "compressor"],
    )
    mock_process = mocker.patch.object(assistant, "_process_query")
    assistant.run()

    mock_process.assert_not_called()
    mock_session.send.assert_called_once_with("what is 2 plus 2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_assistant.py -k claude -v` and `py -m pytest tests/test_action_log.py -k claude -v`
Expected: FAIL — `AttributeError` for `src.assistant.create_session` patch target / missing `log_claude_mode`.

- [ ] **Step 3: Implement `log_claude_mode`**

Append to `src/action_log.py`:

```python
def log_claude_mode(unit: str, event: str, detail: str) -> None:
    _write("claude_mode", unit, mode_event=event, detail=detail)
```

- [ ] **Step 4: Implement the mode in `src/assistant.py`**

Add near the other imports:

```python
import re

from src.integrations.coding_agents import create_session
```

Add below `IDLE_RESET_SECONDS = 30`:

```python
CLAUDE_MODE_LISTEN_TIMEOUT = 300      # seconds per listen while in Claude mode
CLAUDE_MODE_IDLE_EXIT_SECONDS = 900   # continuous silence before auto-exit
_CLAUDE_ENTRY_RE = re.compile(r"^\s*start\s+claude(?:\s+code)?(?:\s+in\s+(?P<name>.+?))?\s*$", re.IGNORECASE)
```

Add these methods to `Assistant` (after `_reset_conversation`):

```python
    def _parse_claude_mode_entry(self, text: str) -> str | None:
        """Return '' for bare 'start claude', the project name for
        'start claude in <name>', or None if this isn't an entry phrase."""
        match = _CLAUDE_ENTRY_RE.match(text)
        if not match:
            return None
        return (match.group("name") or "").strip()

    def _run_claude_mode(self, target_name: str) -> None:
        """Route speech into a coding-agent session until the wake word
        is spoken ALONE (the universal escape), or idle timeout."""
        cfg = self._config.get("coding_agent")
        if not cfg or not cfg.get("default_workdir"):
            self._tts.speak("Claude mode isn't configured on this unit.")
            return

        workdir = cfg["default_workdir"]
        if target_name:
            workdirs = {k.lower(): v for k, v in (cfg.get("workdirs") or {}).items()}
            workdir = workdirs.get(target_name.lower())
            if workdir is None:
                self._tts.speak(f"I don't have a project called {target_name}.")
                return

        session = create_session(cfg)
        session.start(workdir)
        self._tts.speak("Starting Claude.")
        if self._role == "host":
            action_log.log_claude_mode(self._unit_name, "enter", workdir)
        print(f"[Compressor] Claude mode: {workdir} — say '{self._listener.wake_word}' alone to exit.")

        idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
        try:
            while True:
                utterance = self._listener.listen_once(timeout=CLAUDE_MODE_LISTEN_TIMEOUT)
                if not utterance:
                    if time.time() >= idle_deadline:
                        self._tts.speak("Claude mode timed out.")
                        break
                    continue
                # Escape rule: wake word ALONE exits; embedded passes through.
                if utterance.strip().strip(".,!?").lower() == self._listener.wake_word:
                    break
                idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
                print(f"[Claude] > {utterance}")
                self._tts.speak("Working on it.")
                response = session.send(utterance)
                if self._role == "host":
                    action_log.log_claude_mode(self._unit_name, "exchange", f"{utterance} -> {response[:200]}")
                print(f"[Claude] {response}")
                self._tts.speak(response)
                idle_deadline = time.time() + CLAUDE_MODE_IDLE_EXIT_SECONDS
        finally:
            session.stop()
            if self._role == "host":
                action_log.log_claude_mode(self._unit_name, "exit", workdir)
            self._tts.speak("Compressor ready.")
```

In `run()`, at the top of the `while query:` body (before the `print(f"[Assistant] Query received: ...")` line), insert:

```python
                    claude_target = self._parse_claude_mode_entry(query)
                    if claude_target is not None:
                        self._run_claude_mode(claude_target)
                        break  # back to the wake-word loop in normal mode
```

Note: TTS calls inside `_run_claude_mode` are intentionally not wrapped in per-call try/except — the mode's `finally` guarantees session cleanup, and TTS failures already surface loudly in the normal loop. Keep it simple.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -m pytest tests/test_assistant.py tests/test_action_log.py -v`
Expected: PASS (all, including the 10 new)

- [ ] **Step 6: Run the full suite, then commit**

Run: `py -m pytest tests/ -v` — expected 152 passing (142 + 10).

```bash
git add src/assistant.py src/action_log.py tests/test_assistant.py tests/test_action_log.py
git commit -m "Add Claude mode: speech routes to coding-agent session, wake word alone exits"
```

---

### Task 3: Config examples + README section

**Files:**
- Modify: `config.example.yaml`
- Modify: `config.yaml` (LOCAL ONLY — never staged/committed)
- Modify: `README.md`

**Interfaces:**
- Consumes: config shape from Task 2 (`coding_agent:` with `agent`, `model`, `default_workdir`, `workdirs`, `permission_mode`, `max_turns`, `task_timeout_seconds`).
- Produces: documentation only.

- [ ] **Step 1: Append to `config.example.yaml`**

```yaml
# Voice-driven coding agent ("compressor" -> "start claude"). Speech is
# routed into a headless coding-agent session on THIS machine and the
# responses are spoken back. Say the wake word ALONE to exit the mode.
# agent/model are the agent-agnostic seam: v1 supports only claude_code
# (requires the Claude Code CLI installed and authenticated).
coding_agent:
  agent: claude_code
  # model: claude-sonnet-5        # optional; agent's default if unset
  default_workdir: C:\path\to\your\project
  workdirs:                       # spoken names for "start claude in <name>"
    myproject: C:\path\to\your\project
  permission_mode: acceptEdits    # never bypassed; edits auto-approved only in scoped dirs
  max_turns: 25
  task_timeout_seconds: 600
```

- [ ] **Step 2: Append the same block to the LOCAL `config.yaml` with real paths**

Use `default_workdir: C:\git\compressor` and `workdirs: {compressor: C:\git\compressor, jldesigns: C:\git\jldesigns}`. **Do not stage or commit this file**; verify with `git status` that it does not appear.

- [ ] **Step 3: Add a README section**

After the "Programs by voice" section, add (match the file's tone):

```markdown
## Coding by voice (Claude mode)

Say **"Compressor" → "Start Claude"** (or "Start Claude in <project>") and
Compressor becomes a voice interface to a coding agent running on that
machine: everything you say goes straight to the agent as a prompt, and
its responses are spoken back. Say **"Compressor" alone** to exit — the
wake word is the universal escape hatch (embedded mentions of the word
inside a sentence are passed through to the agent).

Configure it with the `coding_agent:` section (see `config.example.yaml`).
The layer is agent-agnostic — which agent and model run come from config;
currently `claude_code` is the only supported agent (requires the
[Claude Code](https://claude.com/claude-code) CLI installed and signed in).
Sessions are scoped to the configured project directory with
auto-approved edits (`acceptEdits`) and never bypass permissions.
```

- [ ] **Step 4: Run the full suite (docs/config-only sanity), verify config.yaml unstaged, commit**

Run: `py -m pytest tests/ -v` — expected same count as after Task 2. Then:

```bash
git add config.example.yaml README.md
git commit -m "Document Claude mode and coding_agent config"
```

---

## Post-implementation notes (not code tasks)

- Live smoke test (user-run): `py main.py` → "compressor" → "start claude" → "what files are in this project" → expect a spoken answer; then "compressor" → "Compressor ready." First real run also validates that `shutil.which("claude")` resolves and `claude -p --output-format json` behaves as mocked.
- The `-p` JSON output shape (`result`, `session_id`) matches Claude Code 2.1.222 as installed; if a future CLI update renames fields, `send()` degrades to the spoken-safe failure string rather than crashing.
- Deferred per spec: mid-task voice cancellation, streaming progress, other agent backends, cross-unit session handoff.
