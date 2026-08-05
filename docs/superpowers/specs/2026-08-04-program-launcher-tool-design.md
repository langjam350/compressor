# Program Launcher Tool with Process Trees and Use-Driven Learning

**Status:** Approved for planning
**Related:** `docs/superpowers/specs/2026-08-02-multi-unit-host-architecture-design.md`
(host/follower architecture this builds on); supersedes the standalone
`C:\git\whisperflow-open-programs` experiment, whose useful ideas (app
registry, already-running check, shell-resolution launching) are absorbed
here.

## Summary

Compressor gains an `open_program` tool: say "compressor, open Brave and
go to YouTube" to any unit, and the program opens **on the machine that
heard the command** — with the requested page/file loaded. Programs are
organized as a two-level tree (program → named processes, where a
process is the argument the program is invoked with). Unknown processes
are executed from Claude's best-guess argument and **learned on first
use** — written back to a per-machine learned file so the tree grows
with usage (the "self-referential loop").

## 1. Tool registry module (new) and tool definition

**Tool schemas move out of `src/ai_client.py` into a new `src/tools.py`.**
The existing `TOOLS` list (`control_tuya_device`, `control_spotify`)
relocates there, and `AIClient` stops importing any tool definitions:
its constructor gains a `tools: list[dict]` parameter
(`AIClient(api_key, system_prompt, tools)`), making it a generic Claude
wrapper with no knowledge of which tools exist. `Assistant` passes
`src/tools.py`'s `TOOLS` when constructing per-unit clients. Existing
`test_ai_client.py` tests update to pass tools explicitly.

New entry in `TOOLS` (now `src/tools.py`):

- Name: `open_program`
- Input schema:
  - `program` (string, required): program to open, e.g. "brave",
    "notepad". Claude normalizes natural phrasing ("my browser" →
    "brave" via alias info in the system prompt).
  - `process` (string, optional): short lowercase name of the action
    inside the program, e.g. "youtube". Claude supplies it whenever the
    user asked for more than a bare launch.
  - `argument` (string, optional): Claude's concrete best-guess argument
    for that process — a URL, file path, or command-line argument, e.g.
    "https://youtube.com". Always supplied alongside `process` so
    unknown processes can still execute (and be learned).
- Description tells Claude: the program opens on the unit the user spoke
  to; known programs/processes for the host are listed in the system
  prompt; for anything else, supply your best-guess `argument`.

`build_system_prompt()` gains a section listing the host's program tree
(names, aliases, and known process names) — same pattern as the
registered-devices list.

## 2. Routing (host decides, requester executes)

All tool calls run on the host (`Assistant._tool_handler`, which already
receives the requesting `unit_name`):

- Requester is the host itself → call the local launcher directly;
  return its real result string (including "already running" and
  failures).
- Requester is a follower → broadcast over the existing WebSocket relay:

  ```json
  {"type": "open_program", "target_unit": "Kitchen",
   "program": "brave", "process": "youtube",
   "argument": "https://youtube.com"}
  ```

  and return an optimistic "Opening … on Kitchen." result.

Follower side: `_handle_network_command` gains an `open_program` case —
ignore unless `target_unit` equals this unit's `unit_name`; otherwise
hand to the local launcher. (This is the first non-Spotify network
command; the handler grows a simple type dispatch.)

**Known v1 limitation:** follower launches are fire-and-forget. The
host's spoken response is optimistic; a failed launch on the follower is
visible only in that follower's log. A result round-trip is an explicit
follow-up, not part of this design.

## 3. Launcher (`src/integrations/launcher.py`, new)

Per-machine program registry from `config.yaml`:

```yaml
programs:
  - name: brave
    launch: brave            # what Windows shell resolution can open
    process_name: brave      # OS process name for already-running check
    aliases: [browser]
    processes:
      youtube: https://youtube.com
```

Starter registry for the host: brave (alias "browser"), notepad,
calculator (`calc` / process `CalculatorApp`), explorer.

Behavior of `ProgramLauncher.open(program, process=None, argument=None) -> str`:

1. **Match program:** exact name → alias → substring fallback (same
   pattern as `TuyaController`). No match → "Program 'X' isn't
   configured on <unit>."
2. **Resolve argument via the tree:** if `process` names a known node
   under that program, **the stored tree value wins** over Claude's
   `argument` (curated/learned behavior stays stable). If `process` is
   unknown but `argument` was supplied, use `argument` — and learn it
   (see §4). If neither, plain launch.
3. **Already-running check** (via `psutil`, new dependency): only for
   bare launches (no argument). With an argument, launching anyway is
   correct — e.g. a URL at a running Brave opens as a new tab.
4. **Launch:** `os.startfile(launch, arguments=...)` (Python ≥3.10) —
   ShellExecute resolution, so "brave" resolves through the Windows App
   Paths registry without a hardcoded install path.
5. Return a human-sensible result string; never raise (mirror
   `TuyaController._safe_control`'s defensive style).

## 4. Use-driven learning (the self-referential loop)

When step 2 executes an unknown `process` from Claude's `argument` and
the launch does not error:

- The mapping `process → argument` is appended under that program in
  `programs_learned.yaml` (repo root on that machine, gitignored),
  silently — the spoken response is just "Opening youtube in brave."
- The learned file is merged with `config.yaml`'s tree at load time;
  `config.yaml` entries win on conflict (hand-curated beats learned).
- Learning happens on whichever unit executed the launch, so each
  machine's tree grows from what is actually used there.
- On the host, a `process_learned` event is written to the action log
  (`action_log.py` gains `log_process_learned(unit, program, process,
  argument)`); follower-side learning appears in the follower's console/
  runtime log only (consistent with the v1 fire-and-forget limitation).
- A failed local launch does not learn.

## 5. Action logging

`open_program` tool calls flow through the existing `log_tool_call`
path, attributed to the requesting unit, like every other tool.

## 6. Error handling

- Launcher never raises; every path returns a result string.
- Follower receiving `open_program` for an unconfigured program logs
  and stays silent (no TTS interruption for a misrouted command).
- Corrupt/missing `programs_learned.yaml` → treated as empty, warning
  printed; next successful learn rewrites it.

## 7. Testing

- `tests/test_launcher.py` (new): program matching (exact/alias/
  substring/none), tree-wins-over-argument, unknown-process-executes-
  argument-and-learns (file written, parseable, merged on next load),
  no-learn-on-failure, already-running skip for bare launch, launch-
  anyway with argument, `os.startfile` called with expected args
  (mocked), never-raises contract.
- `tests/test_assistant.py`: host-requester routes to local launcher;
  follower-requester broadcasts targeted payload and returns optimistic
  text; `_handle_network_command` dispatches `open_program` only when
  `target_unit` matches.
- `tests/test_tools.py` (new): `open_program` present in `src/tools.py`'s
  `TOOLS` with the three-field schema; existing tool schemas intact
  after the move.
- `tests/test_ai_client.py`: updated for the `tools` constructor
  parameter; `AIClient` passes whatever tools it is given to the API
  call (no hardcoded imports).
- System-prompt test: program tree section appears in
  `build_system_prompt` output.

## Non-goals (deferred)

- Trees deeper than two levels (process → sub-process).
- Result round-trip for follower launches.
- Any curation UI for learned processes beyond editing the YAML.
- Non-Windows launch support (os.startfile is Windows-only; the project
  currently targets Windows exclusively).
