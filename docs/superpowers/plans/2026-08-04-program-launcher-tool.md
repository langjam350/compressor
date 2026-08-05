# Program Launcher Tool + Action Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `open_program` voice tool (programs open on the unit that heard the command, with process trees and use-driven learning), while extracting tool schemas into `src/tools.py` and per-action execution into `src/actions/`.

**Architecture:** Three layers — `src/tools.py` holds the schemas Claude sees; `src/actions/` holds one `run(ctx, tool_input) -> str` module per action behind an explicit `ACTIONS` registry; `Assistant._tool_handler` becomes pure dispatch. The new `ProgramLauncher` (`src/integrations/launcher.py`) resolves program→process trees from `config.yaml` merged with a per-machine `programs_learned.yaml`, and learns unknown processes on first successful use. Follower-targeted launches ride the existing WebSocket broadcast with a `target_unit` filter.

**Tech Stack:** Python 3.11 (Windows), pytest + pytest-mock, psutil (new), os.startfile (ShellExecute), PyYAML.

## Global Constraints

- **Claude-facing behavior must not change** except for `open_program` additions: existing schema dicts for `control_tuya_device`/`control_spotify` move verbatim, the system-prompt pattern stays, `AIClient`'s tool-use loop is untouched.
- `open_program` schema: `program` (required string), `process` (optional string), `argument` (optional string).
- Follower launch payload exactly: `{"type": "open_program", "target_unit": <unit>, "program": <p>, "process": <pr>, "argument": <a>}`.
- Tree precedence: `config.yaml` processes win over learned; stored tree wins over Claude's `argument`.
- Already-running check (psutil) ONLY for bare launches (no argument resolved).
- Launcher never raises — every path returns a result string (style of `TuyaController._safe_control`).
- Learned file: `programs_learned.yaml` at repo root, gitignored; corrupt/missing → treated as empty with a printed warning.
- Failed launches do not learn.
- Never commit `config.yaml` (real secrets). The starter `programs:` registry is committed only in `config.example.yaml`; the same block is added to the local `config.yaml` without staging it.
- New dependency: `psutil>=5.9.0` in `requirements.txt`.
- Test suite is currently 91 passing; it must stay green after every task.

---

## File Structure

- Create: `src/tools.py` — all tool schemas (`TOOLS` list).
- Modify: `src/ai_client.py` — remove `TOOLS`; constructor gains optional `tools` param.
- Create: `src/actions/__init__.py` (`ACTIONS` registry), `src/actions/context.py` (`ActionContext`), `src/actions/control_tuya_device.py`, `src/actions/control_spotify.py`, `src/actions/open_program.py`.
- Create: `src/integrations/launcher.py` — `ProgramLauncher`.
- Modify: `src/assistant.py` — dispatch via registry, construct launcher (all roles), pass `TOOLS` to `AIClient`, `_handle_network_command` type dispatch, system-prompt programs section.
- Modify: `src/action_log.py` — `log_process_learned`.
- Modify: `requirements.txt`, `.gitignore`, `config.example.yaml` (+ local-only `config.yaml`).
- Create: `tests/test_tools.py`, `tests/test_actions.py`, `tests/test_launcher.py`. Modify: `tests/test_ai_client.py`, `tests/test_assistant.py`.

---

### Task 1: Extract tool schemas into `src/tools.py`; `AIClient` takes `tools`

**Files:**
- Create: `src/tools.py`
- Modify: `src/ai_client.py`
- Modify: `src/assistant.py:147-162` (`_get_ai_client`)
- Create: `tests/test_tools.py`
- Modify: `tests/test_ai_client.py` (append one test)

**Interfaces:**
- Consumes: current `TOOLS` list at `src/ai_client.py:4-51` (move verbatim).
- Produces: `src.tools.TOOLS: list[dict]`; `AIClient(api_key: str, system_prompt: str, tools: list[dict] | None = None)` — `tools` defaults to `None` → `[]`, is passed as `tools=self._tools` in `messages.create`. `Assistant._get_ai_client` constructs `AIClient(key, prompt, TOOLS)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools.py`:

```python
def test_tools_module_holds_existing_schemas():
    from src.tools import TOOLS
    names = [t["name"] for t in TOOLS]
    assert names == ["control_tuya_device", "control_spotify"]


def test_ai_client_module_has_no_tools_list():
    import src.ai_client as ai_client
    assert not hasattr(ai_client, "TOOLS")
```

Append to `tests/test_ai_client.py`:

```python
def test_client_passes_given_tools_to_api(mocker):
    """AIClient sends whatever tools it was constructed with — no hardcoded imports."""
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.return_value = make_text_response(mocker, "ok")

    my_tools = [{"name": "custom_tool", "input_schema": {"type": "object", "properties": {}}}]

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.", my_tools)
    client.ask("hello", lambda n, i: "")

    assert mock_create.call_args.kwargs["tools"] == my_tools
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_tools.py tests/test_ai_client.py -v`
Expected: `test_tools.py` FAILs with `ModuleNotFoundError: No module named 'src.tools'`; `test_client_passes_given_tools_to_api` FAILs (create called with the old module-level `TOOLS`).

- [ ] **Step 3: Create `src/tools.py`**

Cut the entire `TOOLS = [...]` block from `src/ai_client.py:4-51` and paste it verbatim into a new `src/tools.py` (no other content). Do not edit any schema text.

- [ ] **Step 4: Update `src/ai_client.py`**

Full remaining file content:

```python
from typing import Callable
import anthropic


class AIClient:
    def __init__(self, api_key: str, system_prompt: str, tools: list[dict] | None = None):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._system = system_prompt
        self._tools = tools or []
        self._messages: list[dict] = []

    def reset(self) -> None:
        """Clear conversation history to start a new thread."""
        self._messages = []

    def ask(self, query: str, tool_handler: Callable[[str, dict], str]) -> str:
        self._messages.append({"role": "user", "content": query})

        while True:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self._system,
                tools=self._tools,
                messages=list(self._messages),
            )

            print(f"[AI] stop_reason={response.stop_reason}")
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
                self._messages.append({"role": "assistant", "content": response.content})
                self._messages.append({"role": "user", "content": tool_results})
            else:
                self._messages.append({"role": "assistant", "content": response.content})
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "I couldn't generate a response."
```

- [ ] **Step 5: Wire `TOOLS` through `Assistant`**

In `src/assistant.py`, add to the imports block:

```python
from src.tools import TOOLS
```

and in `_get_ai_client`, change the construction line to:

```python
            client = AIClient(self._config["anthropic_api_key"], self._system_prompt, TOOLS)
```

- [ ] **Step 6: Run the full suite**

Run: `py -m pytest tests/ -v`
Expected: PASS (91 existing + 3 new = 94). The pre-existing `test_ai_client.py` tests construct `AIClient` without `tools` and still pass via the `None` default.

- [ ] **Step 7: Commit**

```bash
git add src/tools.py src/ai_client.py src/assistant.py tests/test_tools.py tests/test_ai_client.py
git commit -m "Extract tool schemas into src/tools.py; AIClient takes tools param"
```

---

### Task 2: `src/actions/` package with registry dispatch

**Files:**
- Create: `src/actions/__init__.py`, `src/actions/context.py`, `src/actions/control_tuya_device.py`, `src/actions/control_spotify.py`
- Modify: `src/assistant.py:188-214` (`_tool_handler`)
- Create: `tests/test_actions.py`

**Interfaces:**
- Consumes: `src.tools.TOOLS` (Task 1); `TuyaController.control(device_name, action) -> str`; `SpotifyController.control(action, query, house_speakers) -> str`; `NetworkClient.broadcast(payload: dict)`.
- Produces: `ActionContext(unit_name, tuya=None, spotify=None, launcher=None, network=None, config=None, host_unit_name="host")` dataclass in `src.actions.context`; `src.actions.ACTIONS: dict[str, Callable[[ActionContext, dict], str]]`; each action module's `run(ctx, tool_input) -> str`. Task 5 adds `open_program` to both `TOOLS` and `ACTIONS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_actions.py`:

```python
def _ctx(mocker, **overrides):
    from src.actions.context import ActionContext
    defaults = dict(
        unit_name="host",
        tuya=mocker.MagicMock(),
        spotify=mocker.MagicMock(),
        launcher=mocker.MagicMock(),
        network=mocker.MagicMock(),
        config={},
        host_unit_name="host",
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def test_registry_stays_in_sync_with_tool_schemas():
    """Every schema Claude can call has exactly one executable action."""
    from src.tools import TOOLS
    from src.actions import ACTIONS
    assert set(ACTIONS.keys()) == {t["name"] for t in TOOLS}
    assert all(callable(fn) for fn in ACTIONS.values())


def test_tuya_action_drives_controller(mocker):
    ctx = _ctx(mocker)
    ctx.tuya.control.return_value = "Lamp turned on."

    from src.actions import control_tuya_device
    result = control_tuya_device.run(ctx, {"device_name": "Lamp", "action": "on"})

    ctx.tuya.control.assert_called_once_with("Lamp", "on")
    assert result == "Lamp turned on."


def test_tuya_action_without_controller_reports_unconfigured(mocker):
    ctx = _ctx(mocker, tuya=None)
    from src.actions import control_tuya_device
    assert control_tuya_device.run(ctx, {"device_name": "Lamp", "action": "on"}) == "Integration not configured."


def test_spotify_action_broadcasts_for_house_speakers(mocker):
    ctx = _ctx(mocker)
    ctx.spotify.control.return_value = "Playing jazz on all house speakers."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "jazz", "house_speakers": True})

    ctx.spotify.control.assert_called_once_with("play", "jazz", house_speakers=True)
    ctx.network.broadcast.assert_called_once_with(
        {"type": "spotify", "action": "play", "query": "jazz"}
    )
    assert "jazz" in result


def test_spotify_action_no_broadcast_without_house_speakers(mocker):
    ctx = _ctx(mocker)
    ctx.spotify.control.return_value = "Playback paused."

    from src.actions import control_spotify
    control_spotify.run(ctx, {"action": "pause"})

    ctx.network.broadcast.assert_not_called()


def test_spotify_action_without_controller_reports_unconfigured(mocker):
    ctx = _ctx(mocker, spotify=None)
    from src.actions import control_spotify
    assert control_spotify.run(ctx, {"action": "pause"}) == "Integration not configured."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.actions'`

- [ ] **Step 3: Create the package**

`src/actions/context.py`:

```python
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ActionContext:
    """Everything an action may need, handed in by Assistant per tool call."""
    unit_name: str
    tuya: Any = None
    spotify: Any = None
    launcher: Any = None
    network: Any = None
    config: Optional[dict] = None
    host_unit_name: str = "host"
```

`src/actions/control_tuya_device.py`:

```python
from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    if ctx.tuya is None:
        return "Integration not configured."
    return ctx.tuya.control(tool_input["device_name"], tool_input["action"])
```

`src/actions/control_spotify.py`:

```python
from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    if ctx.spotify is None:
        return "Integration not configured."
    house = tool_input.get("house_speakers", False)
    result = ctx.spotify.control(
        tool_input["action"],
        tool_input.get("query"),
        house_speakers=house,
    )
    if house and ctx.network is not None:
        ctx.network.broadcast({
            "type": "spotify",
            "action": tool_input["action"],
            "query": tool_input.get("query"),
        })
    return result
```

`src/actions/__init__.py`:

```python
from src.actions import control_spotify, control_tuya_device

ACTIONS = {
    "control_tuya_device": control_tuya_device.run,
    "control_spotify": control_spotify.run,
}
```

- [ ] **Step 4: Rewrite `Assistant._tool_handler` as pure dispatch**

In `src/assistant.py`, add imports:

```python
from src.actions import ACTIONS
from src.actions.context import ActionContext
```

Replace the entire `_tool_handler` method with:

```python
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
            launcher=getattr(self, "_launcher", None),
            network=self._network,
            config=self._config,
            host_unit_name=self._unit_name,
        )
        try:
            result = action(ctx, tool_input)
        except Exception as e:
            result = f"Tool {tool_name} failed ({e})."
        print(f"[Tool] {tool_name} result: {result}")
        action_log.log_tool_call(unit_name, tool_name, tool_input, result)
        return result
```

(`getattr(self, "_launcher", None)` keeps this task independent of Task 5, which introduces the attribute.)

- [ ] **Step 5: Run the full suite**

Run: `py -m pytest tests/ -v`
Expected: PASS. `tests/test_assistant.py`'s existing `test_process_query_logs_query_and_response` and follower/host tests exercise the new dispatch path unchanged from Claude's perspective.

- [ ] **Step 6: Commit**

```bash
git add src/actions/ src/assistant.py tests/test_actions.py
git commit -m "Add src/actions package; _tool_handler becomes registry dispatch"
```

---

### Task 3: `ProgramLauncher` core (match, launch, already-running, never-raise)

**Files:**
- Create: `src/integrations/launcher.py`
- Create: `tests/test_launcher.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing project-internal (stdlib + psutil + yaml).
- Produces: `ProgramLauncher(programs: list[dict], learned_path: str = "programs_learned.yaml", unit_name: str = "host")` with `open(program: str, process: str | None = None, argument: str | None = None) -> str`. Task 4 extends learning; Task 5 wires into `Assistant`.

- [ ] **Step 1: Add dependency and install**

Append to `requirements.txt` after the `numpy` line:

```
psutil>=5.9.0
```

Run: `py -m pip install psutil`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_launcher.py`:

```python
PROGRAMS = [
    {
        "name": "brave",
        "launch": "brave",
        "process_name": "brave",
        "aliases": ["browser"],
        "processes": {"youtube": "https://youtube.com"},
    },
    {"name": "notepad", "launch": "notepad", "process_name": "notepad"},
]


def _launcher(tmp_path, programs=None):
    from src.integrations.launcher import ProgramLauncher
    return ProgramLauncher(
        programs if programs is not None else PROGRAMS,
        learned_path=str(tmp_path / "programs_learned.yaml"),
        unit_name="TestUnit",
    )


def test_exact_name_match_launches(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    mock_start.assert_called_once_with("notepad")
    assert "Opening notepad" in result


def test_alias_match(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("browser")

    mock_start.assert_called_once_with("brave")
    assert "brave" in result.lower()


def test_substring_fallback_match(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    _launcher(tmp_path).open("brave browser")

    mock_start.assert_called_once_with("brave")


def test_unknown_program_reports_unconfigured(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    result = _launcher(tmp_path).open("photoshop")

    mock_start.assert_not_called()
    assert "isn't configured" in result
    assert "TestUnit" in result


def test_bare_launch_skipped_when_already_running(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=True)

    result = _launcher(tmp_path).open("notepad")

    mock_start.assert_not_called()
    assert "already running" in result


def test_known_process_uses_tree_value_over_argument(mocker, tmp_path):
    """Stored tree wins over Claude's best-guess argument."""
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    _launcher(tmp_path).open("brave", process="youtube", argument="https://wrong-guess.example")

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")


def test_argument_launch_skips_already_running_check(mocker, tmp_path):
    """A URL at a running browser opens as a new tab — launch anyway."""
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    running = mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=True)

    _launcher(tmp_path).open("brave", process="youtube", argument=None)

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")
    running.assert_not_called()


def test_launch_failure_returns_string_not_raise(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile", side_effect=OSError("no association"))
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    assert "Couldn't open" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -m pytest tests/test_launcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.integrations.launcher'`

- [ ] **Step 4: Implement `src/integrations/launcher.py`**

```python
import os
from pathlib import Path

import psutil
import yaml

from src import action_log


class ProgramLauncher:
    """Opens configured programs, resolving program -> process trees.

    Never raises: every path returns a human-sensible result string
    (same defensive contract as TuyaController._safe_control).
    """

    def __init__(
        self,
        programs: list[dict],
        learned_path: str = "programs_learned.yaml",
        unit_name: str = "host",
    ):
        # name (lowercased) -> program entry
        self._programs = {p["name"].lower(): p for p in programs}
        self._learned_path = Path(learned_path)
        self._unit_name = unit_name
        self._learned = self._load_learned()

    # ------------------------------------------------------------------ #
    # Matching                                                            #
    # ------------------------------------------------------------------ #

    def _match(self, spoken: str) -> dict | None:
        key = spoken.strip().lower()
        if key in self._programs:
            return self._programs[key]
        for entry in self._programs.values():
            if key in [a.lower() for a in entry.get("aliases", [])]:
                return entry
        for name, entry in self._programs.items():
            if key in name or name in key:
                return entry
        return None

    def _resolve_process(self, program_name: str, entry: dict, process: str | None) -> str | None:
        """Tree lookup: config.yaml processes win over learned ones."""
        if not process:
            return None
        p = process.strip().lower()
        configured = {k.lower(): v for k, v in (entry.get("processes") or {}).items()}
        if p in configured:
            return configured[p]
        learned = {k.lower(): v for k, v in self._learned.get(program_name, {}).items()}
        return learned.get(p)

    def _is_running(self, process_name: str) -> bool:
        target = process_name.lower()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name == target or name == target + ".exe":
                return True
        return False

    # ------------------------------------------------------------------ #
    # Learned-tree persistence (extended in the learning task)            #
    # ------------------------------------------------------------------ #

    def _load_learned(self) -> dict:
        if not self._learned_path.exists():
            return {}
        try:
            data = yaml.safe_load(self._learned_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[Launcher] Could not read {self._learned_path} ({e}) — treating as empty.")
            return {}

    def _learn(self, program_name: str, process: str, argument: str) -> None:
        self._learned.setdefault(program_name, {})[process] = argument
        try:
            self._learned_path.write_text(
                yaml.dump(self._learned, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[Launcher] Could not write {self._learned_path} ({e}).")
        action_log.log_process_learned(self._unit_name, program_name, process, argument)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def open(self, program: str, process: str | None = None, argument: str | None = None) -> str:
        try:
            entry = self._match(program)
            if entry is None:
                return f"Program '{program}' isn't configured on {self._unit_name}."
            name = entry["name"]

            tree_argument = self._resolve_process(name, entry, process)
            final_argument = tree_argument if tree_argument is not None else argument
            is_new_process = bool(process) and tree_argument is None and argument is not None

            if final_argument is None:
                if self._is_running(entry.get("process_name", "")):
                    return f"{name} is already running."
                os.startfile(entry["launch"])
                return f"Opening {name}."

            os.startfile(entry["launch"], arguments=final_argument)
            if is_new_process:
                self._learn(name, process.strip().lower(), argument)
            if process:
                return f"Opening {process.strip().lower()} in {name}."
            return f"Opening {name}."
        except Exception as e:
            return f"Couldn't open {program} ({e})."
```

Note: `action_log.log_process_learned` does not exist until Task 4 — to keep this task green on its own, Task 4 adds it; for THIS task, comment out the `action_log` import and the `log_process_learned` line, both marked with `# enabled in learning task`. (The learning path isn't under test yet in this task.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -m pytest tests/test_launcher.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Run the full suite, then commit**

Run: `py -m pytest tests/ -v` — expected all green.

```bash
git add src/integrations/launcher.py tests/test_launcher.py requirements.txt
git commit -m "Add ProgramLauncher with tree resolution and already-running check"
```

---

### Task 4: Use-driven learning + `log_process_learned`

**Files:**
- Modify: `src/integrations/launcher.py` (enable the two commented lines)
- Modify: `src/action_log.py`
- Modify: `.gitignore`
- Modify: `tests/test_launcher.py` (append), `tests/test_action_log.py` (append)

**Interfaces:**
- Consumes: `ProgramLauncher._learn` (Task 3), `action_log._write` (existing).
- Produces: `action_log.log_process_learned(unit: str, program: str, process: str, argument: str) -> None`; learning behavior verified end-to-end.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_launcher.py`:

```python
import yaml


def test_unknown_process_executes_argument_and_learns(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    learned_file = tmp_path / "programs_learned.yaml"

    launcher = _launcher(tmp_path)
    result = launcher.open("brave", process="reddit", argument="https://reddit.com")

    mock_start.assert_called_once_with("brave", arguments="https://reddit.com")
    assert "reddit" in result
    saved = yaml.safe_load(learned_file.read_text())
    assert saved == {"brave": {"reddit": "https://reddit.com"}}


def test_learned_process_used_on_next_call(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    launcher = _launcher(tmp_path)
    launcher.open("brave", process="reddit", argument="https://reddit.com")
    mock_start.reset_mock()

    # Fresh instance simulates a restart: learned file must be re-read.
    launcher2 = _launcher(tmp_path)
    launcher2.open("brave", process="reddit", argument="https://a-different-guess.example")

    mock_start.assert_called_once_with("brave", arguments="https://reddit.com")


def test_config_processes_win_over_learned(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile")
    (tmp_path / "programs_learned.yaml").write_text(
        yaml.dump({"brave": {"youtube": "https://evil-learned.example"}})
    )

    launcher = _launcher(tmp_path)
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    launcher.open("brave", process="youtube", argument=None)

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")


def test_failed_launch_does_not_learn(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile", side_effect=OSError("boom"))
    learned_file = tmp_path / "programs_learned.yaml"

    launcher = _launcher(tmp_path)
    result = launcher.open("brave", process="reddit", argument="https://reddit.com")

    assert "Couldn't open" in result
    assert not learned_file.exists()


def test_corrupt_learned_file_treated_as_empty(mocker, tmp_path):
    (tmp_path / "programs_learned.yaml").write_text("][ not yaml: [")
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    assert "Opening notepad" in result


def test_learning_writes_action_log_event(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile")
    mock_log = mocker.patch("src.integrations.launcher.action_log.log_process_learned")

    _launcher(tmp_path).open("brave", process="reddit", argument="https://reddit.com")

    mock_log.assert_called_once_with("TestUnit", "brave", "reddit", "https://reddit.com")
```

Append to `tests/test_action_log.py`:

```python
def test_log_process_learned_writes_expected_fields(tmp_path):
    from src import action_log
    log_path = tmp_path / "actions.txt"
    action_log.configure(str(log_path))
    action_log.log_process_learned("Kitchen", "brave", "reddit", "https://reddit.com")

    record = json.loads(log_path.read_text().strip().splitlines()[0])
    assert record["event"] == "process_learned"
    assert record["unit"] == "Kitchen"
    assert record["program"] == "brave"
    assert record["process"] == "reddit"
    assert record["argument"] == "https://reddit.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_launcher.py tests/test_action_log.py -v`
Expected: new launcher tests FAIL (learning lines commented out; `action_log` reference missing); action_log test FAILs with `AttributeError: log_process_learned`.

- [ ] **Step 3: Implement**

In `src/action_log.py`, append:

```python
def log_process_learned(unit: str, program: str, process: str, argument: str) -> None:
    _write("process_learned", unit, program=program, process=process, argument=argument)
```

In `src/integrations/launcher.py`, un-comment the `from src import action_log` import and the `action_log.log_process_learned(...)` call marked `# enabled in learning task`.

Append to `.gitignore`:

```
programs_learned.yaml
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_launcher.py tests/test_action_log.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite, then commit**

```bash
git add src/integrations/launcher.py src/action_log.py .gitignore tests/test_launcher.py tests/test_action_log.py
git commit -m "Learn unknown processes on first successful use"
```

---

### Task 5: `open_program` tool — schema, action, routing, follower handling

**Files:**
- Modify: `src/tools.py` (append schema)
- Create: `src/actions/open_program.py`
- Modify: `src/actions/__init__.py`
- Modify: `src/assistant.py` (construct launcher; `_handle_network_command` dispatch)
- Modify: `tests/test_tools.py`, `tests/test_actions.py`, `tests/test_assistant.py`

**Interfaces:**
- Consumes: `ProgramLauncher.open(program, process=None, argument=None) -> str` (Tasks 3-4); `ActionContext` (Task 2); `NetworkClient.broadcast(payload)`.
- Produces: `open_program` in `TOOLS` and `ACTIONS`; `Assistant._launcher: ProgramLauncher` (all roles); `_handle_network_command` handling `{"type": "open_program", ...}` filtered by `target_unit`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_tools.py`, replace `test_tools_module_holds_existing_schemas` with:

```python
def test_tools_module_holds_all_schemas():
    from src.tools import TOOLS
    names = [t["name"] for t in TOOLS]
    assert names == ["control_tuya_device", "control_spotify", "open_program"]


def test_open_program_schema():
    from src.tools import TOOLS
    schema = next(t for t in TOOLS if t["name"] == "open_program")
    props = schema["input_schema"]["properties"]
    assert set(props) == {"program", "process", "argument"}
    assert schema["input_schema"]["required"] == ["program"]
```

Append to `tests/test_actions.py`:

```python
def test_open_program_local_when_requester_is_host(mocker):
    ctx = _ctx(mocker, unit_name="host", host_unit_name="host")
    ctx.launcher.open.return_value = "Opening youtube in brave."

    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave", "process": "youtube", "argument": "https://youtube.com"})

    ctx.launcher.open.assert_called_once_with("brave", process="youtube", argument="https://youtube.com")
    ctx.network.broadcast.assert_not_called()
    assert result == "Opening youtube in brave."


def test_open_program_broadcasts_to_requesting_follower(mocker):
    ctx = _ctx(mocker, unit_name="Kitchen", host_unit_name="host")

    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave", "process": "youtube", "argument": "https://youtube.com"})

    ctx.launcher.open.assert_not_called()
    ctx.network.broadcast.assert_called_once_with({
        "type": "open_program",
        "target_unit": "Kitchen",
        "program": "brave",
        "process": "youtube",
        "argument": "https://youtube.com",
    })
    assert "Kitchen" in result


def test_open_program_without_launcher_reports_unconfigured(mocker):
    ctx = _ctx(mocker, launcher=None)
    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave"})
    assert "isn't configured" in result
```

Append to `tests/test_assistant.py`:

```python
def test_network_open_program_for_this_unit_launches(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_program", "target_unit": "Kitchen",
        "program": "brave", "process": "youtube", "argument": "https://youtube.com",
    })

    assistant._launcher.open.assert_called_once_with(
        "brave", process="youtube", argument="https://youtube.com"
    )


def test_network_open_program_for_other_unit_ignored(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_program", "target_unit": "Bedroom",
        "program": "brave", "process": None, "argument": None,
    })

    assistant._launcher.open.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_tools.py tests/test_actions.py tests/test_assistant.py -v`
Expected: FAILs — no `open_program` schema/module, `_handle_network_command` ignores the type.

- [ ] **Step 3: Append the schema to `src/tools.py`**

```python
    {
        "name": "open_program",
        "description": (
            "Open a program/application on the computer in the room where the user spoke. "
            "Programs available on the host are listed in the system prompt (other units have "
            "their own lists — attempt the call even for a program not listed). When the user "
            "wants something done inside the program (a website, a file), also give a short "
            "lowercase 'process' name AND your best-guess 'argument' — e.g. going to YouTube "
            "in a browser is process 'youtube' with argument 'https://youtube.com'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "program": {
                    "type": "string",
                    "description": "Program to open, e.g. 'brave', 'notepad'. 'browser' maps to the user's preferred browser."
                },
                "process": {
                    "type": "string",
                    "description": "Short lowercase name for the action inside the program, e.g. 'youtube'"
                },
                "argument": {
                    "type": "string",
                    "description": "Concrete URL, file path, or command-line argument for the process, e.g. 'https://youtube.com'"
                }
            },
            "required": ["program"]
        }
    },
```

- [ ] **Step 4: Create `src/actions/open_program.py`**

```python
from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    program = tool_input["program"]
    process = tool_input.get("process")
    argument = tool_input.get("argument")

    if ctx.unit_name == ctx.host_unit_name:
        if ctx.launcher is None:
            return "Program launching isn't configured on this machine."
        return ctx.launcher.open(program, process=process, argument=argument)

    # Requester is a follower: fire-and-forget targeted broadcast. The
    # spoken response is optimistic — a failed launch is only visible in
    # the follower's own log (known v1 limitation, see design spec).
    if ctx.network is None:
        return "Program launching isn't configured for remote units."
    ctx.network.broadcast({
        "type": "open_program",
        "target_unit": ctx.unit_name,
        "program": program,
        "process": process,
        "argument": argument,
    })
    return f"Opening {process or program} on {ctx.unit_name}."
```

Update `src/actions/__init__.py`:

```python
from src.actions import control_spotify, control_tuya_device, open_program

ACTIONS = {
    "control_tuya_device": control_tuya_device.run,
    "control_spotify": control_spotify.run,
    "open_program": open_program.run,
}
```

- [ ] **Step 5: Wire the launcher and network dispatch in `src/assistant.py`**

Add import:

```python
from src.integrations.launcher import ProgramLauncher
```

In `__init__`, directly after `self._network = NetworkClient(ws_ip, host_port)`, add (all roles — followers execute remote launches locally):

```python
        self._launcher = ProgramLauncher(
            self._config.get("programs", []) or [],
            unit_name=self._unit_name,
        )
```

Replace `_handle_network_command` with:

```python
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
```

In `_tool_handler`, change `launcher=getattr(self, "_launcher", None),` to `launcher=self._launcher,` (the attribute now always exists).

- [ ] **Step 6: Run the full suite**

Run: `py -m pytest tests/ -v`
Expected: PASS, including the Task 2 sync test now covering three tools.

- [ ] **Step 7: Commit**

```bash
git add src/tools.py src/actions/ src/assistant.py tests/test_tools.py tests/test_actions.py tests/test_assistant.py
git commit -m "Add open_program tool: local launch on host, targeted broadcast to followers"
```

---

### Task 6: System-prompt program tree + starter registries

**Files:**
- Modify: `src/assistant.py:22-36` (`build_system_prompt`) and its call site
- Modify: `config.example.yaml`
- Modify: `config.yaml` (LOCAL ONLY — never staged/committed)
- Modify: `tests/test_assistant.py` (append)

**Interfaces:**
- Consumes: `programs` config list shape from Task 3's `PROGRAMS` fixture.
- Produces: `build_system_prompt(location: dict, devices: list[dict], programs: list[dict] | None = None) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assistant.py`:

```python
def test_build_system_prompt_includes_program_tree():
    from src.assistant import build_system_prompt
    prompt = build_system_prompt(
        {"city": "Chicago", "region": "Illinois", "timezone": "America/Chicago"},
        [],
        [
            {"name": "brave", "launch": "brave", "process_name": "brave",
             "aliases": ["browser"], "processes": {"youtube": "https://youtube.com"}},
            {"name": "notepad", "launch": "notepad", "process_name": "notepad"},
        ],
    )
    assert "brave" in prompt
    assert "browser" in prompt      # alias listed
    assert "youtube" in prompt      # known process listed
    assert "notepad" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_assistant.py::test_build_system_prompt_includes_program_tree -v`
Expected: FAIL with `TypeError` (2-arg signature)

- [ ] **Step 3: Extend `build_system_prompt`**

Replace the function with:

```python
def build_system_prompt(location: dict, devices: list[dict], programs: list[dict] | None = None) -> str:
    device_names = ", ".join(d["name"] for d in devices) if devices else "none"
    city = location.get("city", "Unknown")
    region = location.get("region", "Unknown")
    tz = location.get("timezone", "Unknown")

    program_lines = []
    for p in programs or []:
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
```

Update the call site in `Assistant.__init__` (host branch):

```python
            self._system_prompt = build_system_prompt(
                location, devices, self._config.get("programs", []) or []
            )
```

- [ ] **Step 4: Add the starter registry to `config.example.yaml`**

Append:

```yaml
# Programs openable by voice on THIS machine ("compressor, open brave and
# go to youtube"). Each unit (host or follower) has its own list — a
# command spoken to a follower opens the program on that follower.
# processes: named actions inside the program (the launch argument).
# Unknown processes are learned automatically into programs_learned.yaml
# on first successful use.
programs:
  - name: brave
    launch: brave
    process_name: brave
    aliases: [browser]
    processes:
      youtube: https://youtube.com
  - name: notepad
    launch: notepad
    process_name: notepad
  - name: calculator
    launch: calc
    process_name: CalculatorApp
  - name: explorer
    launch: explorer
    process_name: explorer
```

- [ ] **Step 5: Add the same block to the LOCAL `config.yaml`**

Same YAML block appended to `C:\git\compressor\config.yaml`. **Do not `git add` this file** — it holds real secrets and is gitignored; verify with `git status` that it does not appear.

- [ ] **Step 6: Run the full suite**

Run: `py -m pytest tests/ -v`
Expected: PASS. (The pre-existing `test_build_system_prompt_includes_location_and_devices` passes unchanged via the defaulted third parameter.)

- [ ] **Step 7: Commit**

```bash
git add src/assistant.py config.example.yaml tests/test_assistant.py
git commit -m "List program tree in system prompt; add starter program registry"
```

---

## Post-implementation notes (not code tasks)

- Live smoke test on the host: `py main.py`, then "compressor, open brave and go to youtube" → Brave opens YouTube; a second, novel site ("go to reddit") should work AND appear in `programs_learned.yaml` afterward.
- Follower machines need their own `programs:` section (and their own learned file grows independently).
- Deferred per spec: result round-trip for follower launches, trees deeper than two levels, curation UI, non-Windows support.
