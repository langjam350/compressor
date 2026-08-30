# AGENTS.md — Compressor

Canonical context and conventions for any agent working in this repo.
`README.md` is the user-facing setup guide; `FEATURES.md` maps each feature to
the code that implements it. Start here, then go to `FEATURES.md` when you need
to find something.

## What this repository is

**Compressor is James's home assistant.** It is not a library, a demo, or a
product. It is the software that runs the house: one always-on unit per room or
machine, each listening for the wake word "compressor", answering questions,
controlling smart-home devices, playing music, opening programs, and running
scheduled jobs against the home.

Two consequences follow from that, and they shape every decision here:

1. **It has to stay up.** A crash is not a stack trace in a terminal, it is a
   house that stopped responding. Errors degrade to a spoken apology; they do
   not propagate. Every integration is optional and absent-tolerant.
2. **It is spoken, not read.** Responses are 1–3 sentences of plain prose with
   no markdown, because a TTS engine reads them aloud.

## Running a unit

```bash
python main.py "Personal Laptop"
```

The argument is this machine's name and **must** match a `name` in `units.json`.
It is how the unit knows its place in the ownership tier list, how host-side log
entries are attributed, and how targeted commands ("open Brave on the laptop")
find the right machine. `--config` and `--units` override the file paths.

## Ownership: who runs the system, and what happens when they go down

This is the part to understand before changing anything in `src/cluster.py` or
`src/assistant.py`.

### The model

Exactly one unit **owns** the system at a time. The owner is the only unit that
talks to the Anthropic API, holds the integration credentials, runs the
scheduled jobs, and writes the action log. Every other unit is a **follower**: it
captures speech, relays it to the owner over `POST /query`, and speaks back
whatever comes home.

Ownership is not configured, it is **elected**, from a static tier list in
`units.json`:

```json
{
  "units": [
    { "name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100", "host_port": 8765 },
    { "name": "Personal Laptop",  "priority": 2, "host_ip": "192.168.0.166", "host_port": 8765 }
  ]
}
```

Priority 1 is the home unit that should own the system whenever it is online.
Priority 2 stands in while 1 is down, and so on. Priorities must be unique —
that is what makes the ordering total, and a total order is what lets the
election work with no consensus protocol at all: every unit walks the same
sorted list and independently arrives at the same answer.

`units.json` is committed, holds no secrets, and must be **identical on every
unit**. It is the one file the whole cluster agrees on.

### The handover, step by step

Every unit runs the FastAPI server all the time, owner or not, so that peers can
always probe it. `GET /health` returns `{unit_name, owner, priority}`, and
`owner` is the flag that distinguishes a unit doing the job from one that is
merely alive.

- **On startup**, a unit probes every peer *ahead of it* in the tier list, best
  first. If one answers with `owner: true`, the unit becomes a follower pointed
  at that peer. If none answer, it takes ownership itself.
- **Priority 1 never probes anyone** — it has nobody ahead of it, so it takes
  ownership immediately on boot. That is what makes reclaiming automatic rather
  than negotiated.
- **Every 15 seconds** each unit re-runs that decision.
- **Taking over** (the owner went away) requires the peers ahead to miss
  **2 consecutive rounds**, roughly 30 seconds. Promoting on a single dropped
  packet would churn the whole host stack — Tuya connections, Spotify auth,
  scheduler — for nothing.
- **Standing down** (a higher unit came back) happens on the **first** round
  that sees it. Yielding to the rightful owner is always safe, so it is never
  delayed.
- A unit with **no `anthropic_api_key`** is ineligible: it can relay but will
  never promote itself, and it follows the best owner it can find at any
  priority.
- Both transitions are **spoken aloud** ("Taking over as the main unit." /
  "Handing the system back to Personal Desktop.") and written to the action log
  as `ownership` events.

There is a deliberate few-second window during a takeover where two units may
both believe they own the system. For a house, a duplicated device command is a
better failure than a house that has gone silent waiting for a quorum.

### What changes hands

Taking ownership builds Tuya, Spotify, YouTube, the system prompt, and the
scheduler, then flips `app.state.owner` and wires the query handler **last** —
so peers never see `owner: true` from a half-built unit. Standing down does the
reverse: clears the handler, stops the scheduler, drops the integrations, and
re-points the network client at the new owner. Both live in
`Assistant._become_owner` / `_become_follower` and both are idempotent.

Setting `role: host` or `role: follower` in `config.yaml` **pins** the unit and
skips the election entirely. That is a debugging escape hatch and the
backward-compatible path for a unit that must never take over — not the normal
way to run.

## Scheduling jobs

Scheduled jobs are the reason the ownership model exists. A job that fires on
three units at midnight runs three times; electing a single owner means it fires
once, on whichever unit is currently in charge, with automatic failover if that
unit is down at midnight.

### The mechanism

`src/scheduler.py` is a daily-cron loop, deliberately dependency-free. Register
a name, a callable, and a wall-clock time; the loop wakes every 30 seconds,
fires anything whose time has passed today and hasn't run today, and each job
runs on its own daemon thread so a slow one never delays the next poll.

```python
scheduler.register("tuya_sync", lambda: tuya_sync.run(on_complete=...), hour=0)
```

Two properties worth knowing:

- **A late start still runs the day's job.** If the unit boots at noon and a job
  was due at midnight, it fires immediately rather than being skipped. Restarts
  and failovers never silently drop a day.
- **Only the owner schedules.** The `Scheduler` is constructed in
  `_become_owner` and `stop()`ped in `_become_follower`.

### Job contract

A job is one file in `src/tasks/`, exposing a module-level `run(...)` that takes
no required arguments and returns `None`. It logs rather than speaks, tolerates
missing credentials by returning early, and lets the scheduler catch anything it
raises. Optional keyword callbacks are how a job pushes results back into the
running assistant without importing it.

### Existing scheduled jobs

| Job | File | Time | What it does |
|---|---|---|---|
| `tuya_sync` | `src/tasks/tuya_sync.py` | 00:00 daily | Downloads the device list from Tuya cloud, rewrites `tuya-raw.json`, refreshes each device's `local_key`/`ip`/`version` in `config.yaml`, appends devices that are new, then calls `on_complete(devices)` so `Assistant._on_tuya_sync` rebuilds the live `TuyaController` without a restart. Returns early and logs a warning if `tinytuya.json` or `config.yaml` is missing. |

That is the only one today. Registration is currently hardcoded in
`Assistant._become_owner` — see "Structural gaps" below for why that should
become a registry.

## Code conventions

### The system is `src/`

Treat the whole `src/` tree as **the system**. Reading its folder names top to
bottom should tell you what the assistant can do without opening a file. A
capability that isn't visible in the tree is a capability that is hidden.

### Function-oriented, one operation per file

This repo is written for agentic development, which means optimising for a
reader who arrives with no context and needs to change exactly one thing.

- **One operation lives in one Python file.** The file is named after the
  operation. Changing that operation means opening that file and no other.
- **The unit of work is a task, not a class.** Prefer a module-level function
  with an explicit signature over a method hanging off a large object. Classes
  are for things that genuinely hold state across calls (a session, a
  connection pool, a controller wrapping a device SDK), not for grouping
  functions that could stand alone.
- **Tasks are grouped into process folders.** A folder is a process — a coherent
  area of behaviour. Its `__init__.py` is the registry that names the
  operations, and it may hold sibling files that describe the process or do work
  shared across it.

`src/actions/` is the reference implementation of all three rules:

```
src/actions/
  __init__.py            # the registry: ACTIONS maps tool name -> run function
  context.py             # an element describing the process: what every action receives
  control_tuya_device.py # one operation, exposing run(ctx, tool_input) -> str
  control_spotify.py     # one operation
  open_program.py        # one operation
```

Adding a voice action is: add one file with a `run(ctx, tool_input) -> str`, add
one line to the registry. Nothing else moves. New code should aim for that
shape, and `src/tasks/` should read the same way.

### The rest of the house style

- **Never let an exception reach the user as silence.** Catch, log, and return a
  short spoken sentence. `Assistant._speak_safe` exists because even the TTS
  engine dying must not kill a mode.
- **Every integration is optional.** Missing config section, missing package,
  missing credentials — print one clear line saying the feature is off and carry
  on. Never raise at startup for an integration.
- **Comments explain constraints, not mechanics.** The good comments in this
  repo say *why the ordering matters* (query handler wired last) or *why a
  number is what it is*. Don't narrate what the next line does.
- **Tests are pytest, in `tests/test_<module>.py`, run with `pytest tests/`.**
  Mock at the boundary (`mocker.patch("src.assistant.TuyaController")`), name
  tests as the sentence they assert, and cover the failure path — this codebase
  is mostly failure paths.
- **Secrets never enter git.** `config.yaml`, `devices.json`, `snapshot.json`,
  `tuya-raw.json`, and `programs_learned.yaml` are gitignored; `config.example.yaml`
  is the committed template. `units.json` is committed precisely because it must
  hold nothing secret.
  **Outstanding exception:** `tinytuya.json` holds the Tuya cloud `apiKey` and
  `apiSecret` and is *tracked* — it was committed in `3a677a5` and pushed to a
  public remote. Rotate those credentials, then `git rm --cached tinytuya.json`
  and add it to `.gitignore`. Until that is done, do not add anything else to
  that file.
- **Commit subjects are imperative and say what changed**, e.g. "Add Claude
  mode: speech routes to coding-agent session, wake word alone exits". Do not
  commit unless asked.

## Structural gaps

Where the code does not yet meet the conventions above, and how to correct it.
Listed worst-first. None of these are bugs; they are places where finding and
changing one thing costs more than it should.

1. **`src/assistant.py` is ~570 lines and holds at least six operations.**
   Ownership transitions, Claude mode, query processing, tool dispatch, network
   command handling, and the wake loop all live in one class. It is the file
   most likely to be edited and the hardest to edit safely.
   *Correction:* make it a process folder. `src/assistant/__init__.py` keeps a
   thin `Assistant` that owns state and delegates; `ownership.py`,
   `claude_mode.py`, `query.py`, `network_commands.py`, and `system_prompt.py`
   each hold one operation. The seams already exist — the methods are cohesive
   and mostly communicate through `self` plus explicit arguments.

2. **Scheduled jobs have no registry.** `src/tasks/` follows the one-file-per-
   task rule, but registration is hardcoded in `Assistant._become_owner`, so
   adding a job means editing the assistant. This contradicts the pattern
   `src/actions/` already establishes.
   *Correction:* give `src/tasks/__init__.py` a `SCHEDULED_TASKS` registry
   mirroring `ACTIONS` — name, function, hour, minute — and have `_become_owner`
   loop over it. Adding a job becomes: add one file, add one line.

3. **`src/tools.py` duplicates knowledge that belongs to the actions.** The
   Anthropic tool schemas sit in a flat list, physically apart from the action
   files that implement them, so every new action is a two-place edit and they
   can silently drift.
   *Correction:* let each action file export its own `TOOL` schema next to its
   `run`, and have `src/actions/__init__.py` assemble both `ACTIONS` and `TOOLS`
   from the same imports.

4. **`src/integrations/` is flat modules, not process folders.** `spotify.py`
   (~200 lines), `tuya.py`, `youtube.py`, and `launcher.py` are each a
   multi-operation class in a single file.
   *Correction:* worth converting opportunistically rather than in one sweep —
   when you next make a substantial change to one, split it into a folder whose
   `__init__.py` exposes the controller and whose siblings hold the individual
   operations. `spotify.py` is the best first candidate. Do not retro-refactor
   the small ones; that is churn.

5. **Two scripts live outside the system.** `scan_tuya.py` and `test_tts.py` sit
   at the repo root, so they are invisible in the `src/` tree.
   *Correction:* `scan_tuya.py` is an operation and belongs in `src/tasks/`.
   `test_tts.py` is a manual smoke script, not a test — its name means a bare
   `pytest` from the repo root will collect it and make the machine talk. Move
   it out of collection range or delete it, and run tests as `pytest tests/`
   until then.
