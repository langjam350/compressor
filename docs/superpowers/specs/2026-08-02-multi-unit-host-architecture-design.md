# Multi-Unit Host/Follower Architecture, Wake-Word Rename, and Action Logging

**Status:** Approved for planning
**Related:** `business-requirements.txt` (repo root)

## Summary

Compressor becomes a strict host/follower system: exactly one HOST per
household, zero or more FOLLOWERs. The host is the sole unit permitted to
call any external or LAN service (Anthropic API, Spotify API, ipinfo.io,
Tuya cloud resync, direct Tuya device control); followers are thin clients
that only capture audio locally and speak the host's responses. The host
also keeps a detailed, per-unit-attributed action log. The wake word
changes from "condenser"/"condensor" to "compressor," and the wake-word
*detection* mechanism is replaced with a dedicated keyword-spotting engine
(openWakeWord) because the previous approach (matching "condensor" against
Google cloud-STT transcripts) was unreliable.

## 1. Wake word & persona rename

- `config.yaml`'s `wake_word` → `compressor`.
- Every `"Condensor"` / `"Condenser"` string is renamed to `"Compressor"`:
  TTS greeting (`"Condensor ready."` → `"Compressor ready."`), system
  prompt identity in `build_system_prompt()`, and all `[Condensor]`-style
  console log prefixes in `assistant.py` and `stt.py`.
- Test fixtures that hardcode `"condensor"` as the wake word are updated
  to `"compressor"`.

## 2. Config & role model fix

- `src/config_loader.py` currently validates `role == "client"` requires
  `host_ip`, but the rest of the codebase (`assistant.py`, `config.yaml`)
  uses `role: host` vs. an implicit non-host role. This is a live
  validation gap: a follower config missing `host_ip` currently passes
  validation because the check never matches. Fix: validate
  `role == "follower"` instead of `"client"`.
- Add `unit_name` to `config.yaml` — a human-readable identifier (e.g.
  `unit_name: "Living Room"`) used to attribute action-log entries and,
  for followers, to identify the requesting unit to the host. Required
  when `role == "follower"`; defaults to `"host"` when absent and
  `role == "host"`.

## 3. Host: centralized query processing

- `Assistant.__init__` only constructs `AIClient`, `TuyaController`, and
  `SpotifyController` when `role == "host"`. A follower process never
  imports credentials for any of these.
- New private method `Assistant._process_query(unit_name: str, text: str) -> str`
  holds the logic currently inline in `run()` (call `self._ai.ask(text,
  self._tool_handler)`), plus action-log calls (see §5). This is the
  single code path for handling a query — used for the host's own local
  wake events and for every remote follower request — so there is exactly
  one place that talks to Claude and to Tuya/Spotify.
- `src/network/host_server.py` gains `POST /query`:
  - Request: `{"unit_name": str, "text": str}`
  - Response: `{"response": str}`
  - `host_server.py` has no reference to the running `Assistant`, so
    `run_server()` takes a new `query_handler: Callable[[str, str], str]`
    parameter and stores it on `app.state.query_handler`; the endpoint
    calls it. Exceptions are caught inside the endpoint and converted to
    a graceful apology string returned with HTTP 200 (mirrors the
    existing pattern where local errors in `run()` are swallowed into
    "Sorry, something went wrong" rather than crashing) — a follower
    should never have to special-case a 500.
  - `Assistant.__init__` passes `self._process_query` as `query_handler`
    when starting the server thread.
- The existing `/ws` broadcast relay is unchanged — still used for host →
  all-followers push (e.g. house-speaker Spotify sync via
  `NetworkClient.broadcast()`).

## 4. Follower: thin client

- When `role == "follower"`, `Assistant` skips constructing `AIClient`,
  `TuyaController`, and `SpotifyController` entirely.
- `src/network/client.py`'s `NetworkClient` gains:
  ```
  def query(self, unit_name: str, text: str) -> str:
      try:
          resp = httpx.post(f"{self._base}/query",
                             json={"unit_name": unit_name, "text": text},
                             timeout=15.0)
          return resp.json()["response"]
      except Exception:
          return "Sorry, I can't reach the host right now."
  ```
  (Same defensive pattern as the existing `get_info()`.)
- In `Assistant.run()`, the "get a response" step branches on role: host
  calls `self._process_query(self._unit_name, query)` directly; follower
  calls `self._network.query(self._unit_name, query)`.

## 5. Action logging (host only)

- New module `src/action_log.py`: wraps Python's `logging` module with a
  rotating file handler writing JSON Lines to a plain `.txt` file,
  `logs/actions.txt`, in this repo on the host (no SQLite or other DB —
  a text file is sufficient). One
  function per event type:
  - `log_wake(unit_name)`
  - `log_query(unit_name, text)`
  - `log_tool_call(unit_name, tool_name, tool_input, result)`
  - `log_response(unit_name, text)`
  - `log_error(unit_name, context, error)`
  Each writes one line: `{"ts": <iso8601>, "unit": <unit_name>, "event":
  <type>, ...event-specific fields}`.
- Only instantiated/used when `role == "host"`. `_process_query()` and
  `_tool_handler()` call into it at the relevant points, so every action
  taken anywhere in the system — host-originated or follower-originated
  — lands in one file, attributed by `unit_name`.
- Logging calls are wrapped in try/except (print-and-continue on
  failure), matching the existing defensive style used around TTS calls
  in `run()` — a full disk or permissions error must not crash the
  assistant.

## 6. Example data flow

Follower ("Living Room") says "Compressor, turn on the Living Room Light":

1. `stt.py` detects the wake word via openWakeWord (§8) and yields the
   inline query "turn on the Living Room Light".
2. Follower's `run()` calls `self._network.query("Living Room", "turn on
   the Living Room Light")`.
3. `POST /query` on the host → `app.state.query_handler("Living Room",
   "turn on the Living Room Light")` → `Assistant._process_query(...)`.
4. `_process_query` logs the incoming query (`log_query`), calls
   `self._ai.ask(text, self._tool_handler)`.
5. Claude requests the `control_tuya_device` tool; `_tool_handler` calls
   `TuyaController.control(...)`, which flips the physical device over
   the LAN; the tool call and its result are logged (`log_tool_call`).
6. `_process_query` logs the final AI response (`log_response`) and
   returns the confirmation text.
7. `/query` returns `{"response": "Living Room Light turned on."}`.
8. The follower speaks the response via its own local TTS.

## 7. Error handling

- Follower can't reach host (`POST /query` fails/times out) →
  `NetworkClient.query()` returns a fixed apology string; follower speaks
  it via local TTS. No action-log entry (followers don't hold a logger),
  but the follower still prints to console for local debugging, matching
  existing `[STT Error]`/`[TTS Error]` console patterns.
- Host-side processing errors (AI exception, tool exception) are caught
  inside `_process_query`/the `/query` endpoint and converted to an
  apology string returned with HTTP 200, then logged via `log_error`.
- `action_log.py` write failures never propagate — caught and printed,
  never raised.

## 8. Wake-word detection engine (openWakeWord)

- Root cause of the original reliability problem: Phase 1 of
  `SpeechListener.listen_for_commands()` sent 1-second audio chunks to
  Google's cloud STT (`recognize_google`) and regex-matched the wake word
  against the transcript — a general-purpose transcriber being asked to
  reliably spot one uncommon word inside a short window.
- Replace Phase 1 with `openwakeword`, a keyword-spotting engine that
  streams mic audio in small frames through a local ONNX model and scores
  each frame against a threshold — purpose-built for exactly this job,
  and avoids a network round-trip per second.
- **openWakeWord has no pretrained "compressor" model** (its bundled set
  covers phrases like "hey jarvis," "alexa," etc.). A custom model must
  be trained offline using openWakeWord's training pipeline (synthetic
  TTS-generated positive samples + augmentation), producing a small
  `.onnx` file checked into the repo at `models/compressor.onnx`. This is
  a one-time asset-generation step, not runtime logic — flagged as its
  own implementation milestone, separate from the networking/logging
  work, since it has a different kind of risk (model quality/tuning
  rather than code correctness).
- `SpeechListener.__init__` takes a `model_path` pointing at
  `models/compressor.onnx` and runs continuous streaming inference for
  Phase 1 instead of the current listen/transcribe/regex loop.
- **Phase 2 is unchanged** — still `speech_recognition` + Google STT for
  capturing the actual query after wake, since general transcription
  already works acceptably; only wake-word spotting was the problem.
- New dependencies: `openwakeword`, `onnxruntime`.
- Explicitly out of scope for this round: a manual hotkey trigger (e.g.
  Ctrl+' or Ctrl+T) as an alternate activation method — considered and
  declined; voice-only for now.

## 9. Testing

- `test_config_loader.py`: update the `"client"` role test case to
  `"follower"`.
- `test_network.py`: new tests for `POST /query` (mock `query_handler`
  injected via `app.state`) and `NetworkClient.query()` (mock
  `httpx.post`, both success and failure/timeout paths).
- `test_assistant.py`: new tests asserting a follower-role `Assistant`
  never constructs `AIClient`/`TuyaController`/`SpotifyController`, and
  that its query-handling path calls `NetworkClient.query()` instead of
  `AIClient.ask()` directly. Existing host-role tests updated for the
  `_process_query` refactor and renamed wake word fixtures.
- New `test_action_log.py`: writes to a temp path, asserts each log
  function produces exactly one well-formed, parseable JSON line with
  the expected fields.
- New tests for the openWakeWord-based Phase 1 (mocking the model's
  frame-scoring call rather than real audio) covering: score-above-
  threshold triggers `on_wake`/proceeds to Phase 2, score-below-threshold
  is ignored.

## Non-goals for this round

- Manual hotkey activation (Ctrl+' / Ctrl+T) — declined.
- Access to Wispr Flow's transcription stream — not feasible; Wispr Flow
  has no documented local API for this.
- SQLite or other queryable storage for the action log — JSONL is
  sufficient for now; revisit if ad-hoc querying becomes a real need.
