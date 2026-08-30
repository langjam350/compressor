# FEATURES.md — where each feature lives

A map from what Compressor does to the code that does it. Use it to find the
right file fast; use `AGENTS.md` for the conventions those files follow.

Line numbers drift as the code changes. Function and class names don't — if a
line number looks wrong, search for the symbol name in the same file and update
the entry.

---

## 1. Voice pipeline — wake word to spoken answer

The loop every other feature hangs off.

| Part | Where |
|---|---|
| Main loop: wake, capture, dispatch, speak, follow up | `src/assistant.py:537` (`Assistant.run`) |
| Wake-word listening (streaming, openWakeWord) | `src/stt.py:57` (`SpeechListener._listen_openwakeword`) |
| Wake-word listening (cloud-STT fallback, no model file) | `src/stt.py:114` (`SpeechListener._listen_google`) |
| Engine choice between the two | `src/stt.py:43` (`SpeechListener.listen_for_commands`) |
| Stripping the wake word out of an utterance | `src/stt.py:20` (`extract_query`) |
| One-shot listen for a follow-up or Claude-mode turn | `src/stt.py:173` (`SpeechListener.listen_once`) |
| "Yes?" acknowledgement on wake | `src/assistant.py:276` (`Assistant._on_wake`) |
| Text to speech | `src/tts.py:52` (`TTSEngine.speak`) |
| TTS that must never kill the caller | `src/assistant.py:373` (`Assistant._speak_safe`) |
| Conversation continues without re-waking, then resets | `src/assistant.py:543` loop; idle window `src/assistant.py:29` |

## 2. Ownership and failover

Which unit runs the system, and the handover when it changes. Concept and
rationale are in `AGENTS.md`.

| Part | Where |
|---|---|
| The tier list itself | `units.json` |
| Tier list loading and validation | `src/cluster.py:80` (`UnitRegistry.load`) |
| Rejecting duplicate names / priorities | `src/cluster.py:56` (`UnitRegistry.__init__`) |
| Units ranked ahead of this one | `src/cluster.py:124` (`UnitRegistry.ahead_of`) |
| Is a peer up *and* claiming ownership? | `src/cluster.py:133` (`probe`) |
| The election decision | `src/cluster.py:189` (`Coordinator.decide`) |
| One re-election round, with the promotion delay | `src/cluster.py:230` (`Coordinator.run_round`) |
| Background watch loop | `src/cluster.py:226` (`Coordinator._watch`), poll interval `src/cluster.py:33` |
| How many missed rounds before taking over | `src/cluster.py:38` (`PROMOTE_AFTER_MISSES`) |
| Startup: election plus eligibility check | `src/assistant.py:133` (`Assistant._elect`) |
| Applying a decision | `src/assistant.py:169` (`Assistant._apply_owner`) |
| Taking ownership (builds the host stack) | `src/assistant.py:185` (`Assistant._become_owner`) |
| Standing down (tears it back down) | `src/assistant.py:246` (`Assistant._become_follower`) |
| Ownership advertised to peers | `src/network/host_server.py:48` (`GET /health`) |
| Re-pointing at a new owner | `src/network/client.py:20` (`NetworkClient.set_host`) |
| Pinned-role escape hatch | `src/assistant.py:133`, validated in `src/config_loader.py:28` |
| Unit name from the command line | `main.py:14` |
| Ownership events in the log | `src/action_log.py:70` (`log_ownership`) |

## 3. Scheduled jobs

| Part | Where |
|---|---|
| The daily-cron loop | `src/scheduler.py:59` (`Scheduler._loop`) |
| Firing whatever is due (the testable pass) | `src/scheduler.py:64` (`Scheduler.fire_due`) |
| Registering a job | `src/scheduler.py:35` (`Scheduler.register`) |
| Poll interval (30s) | `src/scheduler.py:29` (`Scheduler._CHECK_INTERVAL`) |
| Each job on its own thread, exceptions swallowed | `src/scheduler.py:94` (`Scheduler._run_task`) |
| Stopping when this unit stands down | `src/scheduler.py:52` (`Scheduler.stop`) |
| Where jobs are registered today | `src/assistant.py:226` (inside `_become_owner`) |
| **Job: `tuya_sync`** — daily 00:00 Tuya cloud refresh | `src/tasks/tuya_sync.py:23` (`run`) |
| Live `TuyaController` reload after that sync | `src/assistant.py:288` (`Assistant._on_tuya_sync`) |

## 4. AI and tool calling

| Part | Where |
|---|---|
| Anthropic client and the tool-use loop | `src/ai_client.py:16` (`AIClient.ask`) |
| System prompt (location, devices, programs) | `src/assistant.py:35` (`build_system_prompt`) |
| Tool schemas sent to the model | `src/tools.py:1` (`TOOLS`) |
| Tool name to implementation | `src/actions/__init__.py:3` (`ACTIONS`) |
| Dispatching a tool call | `src/assistant.py:516` (`Assistant._tool_handler`) |
| What every action receives | `src/actions/context.py:6` (`ActionContext`) |
| One query end to end | `src/assistant.py:498` (`Assistant._process_query`) |
| Per-unit conversation isolation | `src/assistant.py:342` (`Assistant._get_ai_client`) |
| Per-unit request serialisation | `src/assistant.py:328` (`Assistant._get_unit_lock`) |
| Conversation reset after 30s idle | `src/assistant.py:354`, constant at `src/assistant.py:29` |

## 5. Smart home (Tuya)

| Part | Where |
|---|---|
| Voice action | `src/actions/control_tuya_device.py:4` (`run`) |
| Tool schema | `src/tools.py:3` |
| Controller | `src/integrations/tuya.py:32` (`TuyaController`) |
| Single device on/off | `src/integrations/tuya.py:58` (`_control_single`) |
| "All the lights" / room grouping | `src/integrations/tuya.py:44` (`_find_devices_by_category`) |
| Parallel control with a concurrency cap | `src/integrations/tuya.py:100` (`_control_many`), cap at `:10` |
| Per-device failure isolation | `src/integrations/tuya.py:89` (`_safe_control`) |
| Device list | `config.yaml` under `tuya.devices` |

## 6. Music — Spotify, with a YouTube fallback

| Part | Where |
|---|---|
| Voice action (play, pause, next, app start/stop) | `src/actions/control_spotify.py:35` (`run`) |
| Tool schema | `src/tools.py:26` |
| Spotify controller | `src/integrations/spotify.py:37` (`SpotifyController`) |
| Search and match scoring | `src/integrations/spotify.py:91` (`search_best`), threshold at `:16` |
| Playback onto a device | `src/integrations/spotify.py:144` (`play_item`) |
| House-speaker device selection | `src/integrations/spotify.py:59` (`_get_device_ids`) |
| Waiting for the app to appear as a Connect device | `src/integrations/spotify.py:68` (`_wait_for_devices`) |
| Starting/stopping the desktop app | `src/integrations/spotify_app.py:29` / `:39` |
| Starting the app on every unit at once | `src/assistant.py:281` (`_start_spotify_everywhere`) |
| YouTube fallback when no good Spotify match | `src/actions/control_spotify.py:6` (`_play_youtube`) |
| YouTube resolution (channel default, then search) | `src/integrations/youtube.py:114` (`YouTubeSearcher.resolve`) |
| Channel shortcuts | `config.yaml` under `youtube.channel_defaults` |

## 7. Opening programs

| Part | Where |
|---|---|
| Voice action | `src/actions/open_program.py:4` (`run`) |
| Tool schema | `src/tools.py:66` |
| Launcher | `src/integrations/launcher.py:104` (`ProgramLauncher.open`) |
| Spoken name and alias matching | `src/integrations/launcher.py:39` (`_match`) |
| Named sub-actions ("open Brave and go to YouTube") | `src/integrations/launcher.py:53` (`_resolve_process`) |
| Learning an unknown process on first use | `src/integrations/launcher.py:88` (`_learn`) → `programs_learned.yaml` |
| Already-running detection | `src/integrations/launcher.py:64` (`_is_running`) |
| Opening on a *different* unit | `src/assistant.py:293` (`_handle_network_command`) |

## 8. Claude mode — voice-driven coding agent

| Part | Where |
|---|---|
| Entry phrase ("start claude", "start claude in <project>") | `src/assistant.py:32` (regex), `:365` (`_parse_claude_mode_entry`) |
| The mode itself: background worker, queueing, exit, cleanup | `src/assistant.py:381` (`_run_claude_mode`) |
| Exit rule — wake word spoken alone | `src/assistant.py:350` region inside that method |
| Idle timeout / listen chunking | `src/assistant.py:30`–`31` |
| Agent-agnostic session interface | `src/integrations/coding_agents/__init__.py:10` (`CodingAgentSession`) |
| Session factory | `src/integrations/coding_agents/__init__.py:36` (`create_session`) |
| Claude Code implementation | `src/integrations/coding_agents/claude_code.py:16` |
| Sending a task and streaming activity | `claude_code.py:50` (`send`), `:136` (`_handle_event`) |
| Cancelling in-flight work on exit | `claude_code.py:123` (`cancel`) |
| Voice-shaped system prompt | `claude_code.py:6` (`VOICE_SYSTEM_PROMPT`) |
| Config | `config.yaml` under `coding_agent` |

## 9. Multi-unit networking

| Part | Where |
|---|---|
| Server (runs on every unit) | `src/network/host_server.py:88` (`run_server`) |
| Follower relays a query to the owner | `src/network/host_server.py:58` (`POST /query`), client at `src/network/client.py:52` |
| Health / ownership probe | `src/network/host_server.py:48` (`GET /health`) |
| Geolocation for the system prompt | `src/network/host_server.py:34` (`GET /info`) |
| WebSocket relay between units | `src/network/host_server.py:70` (`/ws`) |
| Client WS connect with backoff | `src/network/client.py:72` (`_run_ws_loop`) |
| Broadcasting to other units | `src/network/client.py:96` (`broadcast`) |
| Handling a broadcast (Spotify, open URL, open program) | `src/assistant.py:293` (`_handle_network_command`) |

## 10. Action log

| Part | Where |
|---|---|
| Setup, rotation, JSON Lines format | `src/action_log.py:11` (`configure`) → `logs/actions.txt` |
| Record writer | `src/action_log.py:31` (`_write`) |
| Event types | `src/action_log.py:46`–`75`: wake, query, tool_call, response, error, process_learned, ownership, claude_mode |

## 11. Configuration

| Part | Where |
|---|---|
| Loading and validation | `src/config_loader.py:10` (`load_config`) |
| Required keys | `src/config_loader.py:3` (`REQUIRED_KEYS`) |
| Pinned-role validation (optional path) | `src/config_loader.py:28` |
| Committed template | `config.example.yaml` |
| Cluster tier list | `units.json` (committed — contains no secrets) |
| Secret-bearing files, gitignored | `config.yaml`, `devices.json`, `snapshot.json`, `tuya-raw.json`, `programs_learned.yaml` |
| Tuya cloud credentials, **tracked — see AGENTS.md** | `tinytuya.json` (read by `src/tasks/tuya_sync.py:30`) |
