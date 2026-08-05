# Voice-Driven Claude Code Mode

**Status:** Approved design, pending user review of this document
**Related:** `docs/superpowers/specs/2026-08-04-program-launcher-tool-design.md`
(actions architecture), `docs/superpowers/specs/2026-08-02-multi-unit-host-architecture-design.md`
(host/follower model)

## Summary

A dedicated **Claude mode**: say "Compressor" → "Start Claude" and every
subsequent utterance is routed straight into a persistent Claude Code
session running on the machine that heard it — speech becomes the
prompt, Claude Code's final text is spoken back through TTS. The mode
runs until the wake word is spoken **alone**, which exits back to
normal assistant operation with "Compressor ready." The wake word is
the universal escape hatch: one word always brings you home.

## 1. UX flow (canonical exchange)

```
You:  "Compressor"                  → "Yes?"
You:  "Start Claude"                → "Starting Claude."        [CLAUDE MODE]
You:  "add a dark mode toggle to the site"
                                    → "Working on it."
                                    → (session runs, may take minutes)
                                    → speaks Claude Code's response
You:  "now persist the choice in local storage"
                                    → same session resumes; speaks result
You:  "Compressor"                  → "Compressor ready."       [NORMAL MODE]
```

- Inline entry also works: "Compressor, start Claude" (single utterance).
- Optional project targeting: "Start Claude in jldesigns" selects a
  configured working directory (see §5); bare "Start Claude" uses the
  default workdir.

## 2. Mode state machine (in `Assistant.run()`)

Mode entry is **deterministic phrase matching, not an AI tool call**:
if a captured query (normal flow) case-insensitively matches
`start claude` or `start claude in <name>`, the run loop enters Claude
mode directly — no Claude-API round trip, no entry in `TOOLS`/`ACTIONS`.
Rationale: mode switching must be instant, free, and never
misinterpreted by the assistant model.

Inside Claude mode the loop bypasses wake-word gating entirely:
repeatedly `listen_once(timeout=CLAUDE_MODE_LISTEN_TIMEOUT)` (long
timeout, e.g. 300s so the mode survives thinking pauses), and for each
utterance:

1. **Escape check:** if the utterance, stripped and lowercased, equals
   the wake word exactly (`"compressor"`) → exit the mode: stop the
   session wrapper, speak "Compressor ready.", return to the normal
   wake loop. **The wake word embedded in a longer sentence does NOT
   exit** — "add a test to compressor's launcher" passes through to
   Claude Code verbatim (approved rule: alone-only escape, since this
   very repo is named compressor).
2. Otherwise: speak "Working on it.", call
   `session.send(utterance)` (blocking; v1 is synchronous — the mic is
   not captured while a task runs), then speak the returned text.
3. On listen timeout with no speech: stay in the mode silently (the
   user may be reading/thinking); after
   `CLAUDE_MODE_IDLE_EXIT` (e.g. 15 minutes) of continuous silence,
   auto-exit with "Claude mode timed out. Compressor ready."

The mode is **local to the unit that heard it** — like `open_program`,
the session runs on that machine. It never routes through the host's
`/query` path: a follower entering Claude mode runs Claude Code
locally. If the `claude` CLI is missing on the machine, entry fails
with a spoken "Claude Code isn't installed on this unit."

## 3. Session layer — agent-agnostic interface, Claude Code as first backend

The session abstraction is **AI-agent agnostic by design**: the mode
talks only to a generic interface, and which coding agent (and which
model) gets used comes from configuration, not code. The intent is
that integrations for the major coding agents (Claude Code, and later
others — e.g. Codex CLI, Gemini CLI, Aider) can slot in behind the
same interface. **v1 implements exactly one backend, Claude Code —
no others are built now**; the seam just has to exist so adding one
later means writing a new backend file plus a config value, touching
nothing in the mode logic.

`src/integrations/coding_agents/__init__.py` — the interface and a
registry:

- `CodingAgentSession` (protocol/base): `start(workdir: str) -> None`,
  `send(text: str) -> str`, `stop() -> None`. `send()` never raises —
  errors come back as spoken-safe strings.
- `create_session(agent_config: dict) -> CodingAgentSession` — factory
  keyed on `agent_config["agent"]` (v1: only `"claude_code"`; unknown
  values → a stub session whose `send` returns "Coding agent '<name>'
  isn't supported on this unit."). The factory passes through
  config-supplied parameters (model, permission mode, turn/timeout
  limits) so backends are parameterized entirely from `config.yaml`.

`src/integrations/coding_agents/claude_code.py` — the one v1 backend:
wraps headless one-shot invocations, NOT a live terminal bridge (the
interactive TUI's spinners/ANSI/permission dialogs are hostile to
scraping; `-p` returns clean final text with identical capability):

- `start(workdir: str) -> None` — records the workdir; no process yet.
- `send(text: str) -> str` — runs:

  ```
  claude -p <text> --output-format json
         [--model <configured model, omitted if unset>]
         [--resume <session_id> on second and later calls]
         --permission-mode <configured, default acceptEdits>
         --add-dir <workdir> (cwd also set to workdir)
         --max-turns <configured, default 25>
         --append-system-prompt "Your final response will be spoken
         aloud through text-to-speech. Keep it under 3 sentences,
         plain prose, no markdown or code unless asked to read code."
  ```

  Parses the JSON result: captures `session_id` on first use (enables
  `--resume` continuity for every later utterance), returns the
  `result` text. Timeout: `CLAUDE_MODE_TASK_TIMEOUT` (default 600s);
  on timeout kill the process and return "That task timed out."
- `stop() -> None` — terminates any in-flight process; drops session id.
- Never raises from `send()` — errors (CLI missing, non-zero exit,
  JSON parse failure, timeout) come back as spoken-safe strings, same
  defensive contract as `ProgramLauncher.open`.

## 4. Safety rails

- **Scoped filesystem:** the session's cwd/`--add-dir` is only the
  configured workdir. No `--dangerously-skip-permissions`, ever.
- **Permission mode:** `acceptEdits` default (file edits in the scoped
  dir auto-approved; anything beyond needs `allowed_tools` config).
  Configurable per install.
- **Explicitly logged:** on the host, entering/exiting the mode and
  every prompt/response pair is written to the action log
  (`log_claude_mode(unit, event, detail)` added to `action_log.py`).
  Followers print to console/runtime log.
- The mode never runs concurrently with normal queries on the same
  unit (single-threaded run loop already guarantees this).

## 5. Config (`config.yaml`, per machine)

```yaml
coding_agent:
  agent: claude_code       # which backend the factory builds (v1: only claude_code)
  model:                   # optional; passed to the backend (e.g. claude --model); agent default if unset
  default_workdir: C:\git\compressor
  workdirs:                # spoken names for "start claude in <name>"
    jldesigns: C:\git\jldesigns
    compressor: C:\git\compressor
  permission_mode: acceptEdits
  max_turns: 25
  task_timeout_seconds: 600
```

Section optional — absent config means "Start Claude" responds
"Claude mode isn't configured on this unit." Committed example goes in
`config.example.yaml` with placeholder paths. The `agent`/`model` keys
are the agent-agnostic seam (§3): the mode never hardcodes a vendor;
swapping coding agents later is a config change plus one backend file.

## 6. Error handling

- CLI missing / config absent → spoken refusal at entry; stay in
  normal mode.
- `send()` failure mid-mode → speak the error string; **stay in the
  mode** (user can retry or escape with the wake word).
- STT errors during the mode → same as normal loop (ignore, keep
  listening).
- Exit always speaks "Compressor ready." so the user knows which mode
  they're in.

## 7. Testing

- `tests/test_coding_agents.py` (new): factory returns the Claude Code
  backend for `agent: claude_code`, parameterized from config (model,
  permission mode, limits); unknown agent name → stub session with the
  spoken-safe unsupported message; `send()` builds the expected
  command (first call no `--resume`, later calls with captured session
  id; `--model` present only when configured — mock `subprocess.run`);
  JSON parse of result/session_id; timeout → kill + spoken-safe
  string; CLI error → spoken-safe string; never-raises contract.
- `tests/test_assistant.py`: "start claude" phrase enters the mode
  (session started with default workdir); "start claude in jldesigns"
  maps the named workdir; wake word ALONE exits (session.stop called,
  "Compressor ready." spoken); wake word embedded in a sentence is
  forwarded to `session.send`, not treated as exit; missing config →
  spoken refusal, no mode entry.

## Non-goals (deferred)

- **Additional coding-agent backends** (Codex CLI, Gemini CLI, Aider,
  etc.) — the agent-agnostic interface and config seam ship in v1, but
  only the Claude Code backend is implemented. Do not build others now.
- Interrupting/cancelling an in-flight task by voice (v1 blocks while
  a task runs; the escape word works only between tasks).
- Streaming progress narration (`--output-format stream-json` exists
  for this later).
- Multiple concurrent sessions or cross-unit session handoff.
- Permission prompts by voice (pre-authorization only).
