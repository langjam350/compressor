# Design: Conversation Threading + Tuya Decision Matrix

**Date:** 2026-03-02
**Status:** Approved

---

## Problem

1. **Apparent shutdown** — after processing a Claude query the assistant returns to silent
   wake-word listening with no output, making it appear to have crashed.

2. **Single-turn only** — every query starts a fresh Claude context; follow-up questions
   ("what about the bedroom ones?", "now turn them off") lose all prior context.

3. **Single-device Tuya control** — `control_tuya_device` can only target one device per
   call; "turn on the lights" fails to control the full device fleet.

---

## Solution Overview

Three coordinated changes across four files:

| Concern | File(s) |
|---------|---------|
| Bug fix + conversation loop | `src/assistant.py` |
| Persistent conversation history | `src/ai_client.py` |
| Post-response follow-up listening | `src/stt.py` |
| Category-based bulk device control | `src/integrations/tuya.py`, `src/ai_client.py` |

---

## Section 1 — Bug Fix (apparent shutdown)

`stt.py:26` prints `[Condensor] Listening for wake word '...']` once at startup. After any
processed query the generator loops silently via `WaitTimeoutError → continue`, so the
user sees no activity.

**Fix:** Print the listening message in `run()` immediately after the conversation thread
ends. Also wrap the outer `for` loop in a broad `except Exception` so unexpected crashes
surface with a traceback instead of silently exiting.

---

## Section 2 — Conversation Threading

### Flow

```
wake word → initial query
                │
                ▼
          Claude (full history)
                │
                ▼
          TTS response
                │
                ▼
       listen_once(timeout=5)
         /            \
   speech heard      5s timeout
        │                 │
   (loop back)      ai.reset()
                    print "Listening..."
```

### `stt.py` — `listen_once(timeout, phrase_time_limit)`

New method on `SpeechListener`. Opens mic, waits up to `timeout` seconds, returns
recognized text or `None`. No wake-word check — any speech continues the thread.

```python
def listen_once(self, timeout: float = 5, phrase_time_limit: float = 10) -> str | None:
```

### `ai_client.py` — persistent history

`AIClient` gains `self._messages: list[dict] = []`. `ask()` appends each turn
(user message, assistant content, tool exchanges) so every call within a thread has
full prior context. New `reset()` method clears the list. External interface unchanged
(`ask()` still returns `str`).

### `assistant.py` — inner conversation loop

`run()` changes from a flat for-loop to a nested structure:

```python
for initial_query in self._listener.listen_for_commands():
    query = initial_query
    while query:
        response = self._ai.ask(query, self._tool_handler)
        self._tts.speak(response)
        print("[Assistant] Done.")
        query = self._listener.listen_once(timeout=5)
    self._ai.reset()
    print(f"[Condensor] Listening for wake word '{self._listener.wake_word}'...")
```

---

## Section 3 — Tuya Decision Matrix

### Category matching

`TuyaController.control()` first tries the existing `_find_device()` (exact + fuzzy).
If no match, it calls `_find_devices_by_category()`, which scans all device names for
keyword matches:

| Query term | Matches device names containing |
|------------|----------------------------------|
| `lights` / `light` | `light`, `lamp`, `bulb` |
| `lamps` / `lamp` | `lamp` |
| `bulbs` / `bulb` | `bulb` |
| `fans` / `fan` | `fan` |
| `all` | every device |

Multi-word categories are AND-matched: `"bedroom lights"` requires both `bedroom` and
one of the light keywords in the device name.

### Behaviour

- Single match → existing single-device path (no change).
- Multiple matches → control each device, return summary:
  `"Controlled 8 device(s): Living Room Light turned on; ..."`.
- No matches → existing not-found message.

### Tool description update (`ai_client.py`)

```
device_name can be a specific device name (e.g. 'Living Room Light') OR a category
such as 'lights', 'bedroom lights', 'fans', or 'all'.
```

---

## Files Changed

| File | Change |
|------|--------|
| `src/stt.py` | Add `listen_once()` |
| `src/ai_client.py` | Persistent `_messages`, `reset()`, updated tool description |
| `src/integrations/tuya.py` | `_find_devices_by_category()`, fallback in `control()` |
| `src/assistant.py` | Inner conversation loop, listening feedback message |

---

## Testing

- `tests/test_stt.py` — add tests for `listen_once`: speech detected, timeout, error
- `tests/test_tts.py` — no changes needed
- `tests/test_ai_client.py` — test history accumulation across turns, `reset()` clears state
- `tests/test_tuya.py` — test category matching: exact, multi-word, no match, all
