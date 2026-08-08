# Compressor

A self-hosted, multi-room voice assistant for Windows — an Alexa-style
system you run on your own computers. One machine acts as the **host**
(the only unit holding API keys and talking to the outside world); any
number of **follower** machines in other rooms relay voice commands to
it over your LAN and speak the responses locally.

**Who it's for:** tinkerers who want a private, hackable home voice
assistant built from machines they already own — with smart-home
control (Tuya devices), Spotify, program launching by voice, and a
general-purpose AI brain (Claude) — without shipping their household
audio to a big-box smart speaker.

**What it does today:**
- Wake word ("compressor") with on-device openWakeWord detection
  (cloud-STT fallback until you train the model — see
  [docs/WAKE-WORD-TRAINING.md](docs/WAKE-WORD-TRAINING.md))
- Natural-language smart-home control of Tuya lights/plugs on your LAN
- Spotify playback, including house-wide playback across units
- Opens programs by voice on whichever machine you spoke to
  ("compressor, open Brave and go to YouTube") — and learns new
  program actions the first time you use them
- Per-unit conversation isolation and a host-side action log of
  everything the system did

---

## Architecture

```
[Host machine]  ←──── runs FastAPI server (port 8765)
    │                  handles AI, Tuya, Spotify
    │                  broadcasts commands to followers via WebSocket
    │
    └──── [Follower machine]  ←── listens for wake word
    └──── [Follower machine]  ←── plays back Spotify on local device
```

The **Host** runs the AI and integration logic and is the only machine that needs an Anthropic API key — **Followers** hold zero Anthropic credentials. A Follower captures a spoken command, sends it to the Host over `POST /query` (`{unit_name, text}` in, `{response}` out), and speaks back whatever the Host returns. Followers also stay connected to the Host over WebSocket so that "play everywhere" commands and targeted actions (like opening a program on a specific follower) can be broadcast to the right unit.

Wake-word detection runs locally on every unit via [openWakeWord](https://github.com/dscripka/openWakeWord) once you've trained a model for "compressor" (see [docs/WAKE-WORD-TRAINING.md](docs/WAKE-WORD-TRAINING.md)); until then, each unit falls back to cloud speech-to-text for wake detection.

Note: the Host keeps each unit's conversation history in memory only. Restarting the Host clears all in-progress conversation context for every unit — a follow-up like "what about the bedroom?" won't be understood as a continuation after a Host restart.

The Host also writes a running log of every wake, query, tool call, and error across all units to `logs/actions.txt`, tagged by `unit_name`.

---

## Requirements

- Python 3.11+
- Microphone on each machine running Compressor
- All machines on the same LAN
- [Anthropic API key](https://console.anthropic.com) — Host only
- Tuya IoT account (for smart device control)
- Spotify Developer app (for music control)

---

## Installation

Run this on **every machine** (host and followers):

```bash
pip install -r requirements.txt
```

---

## Configuration

Copy the example config and edit it:

```bash
cp config.example.yaml config.yaml
```

### Host config (`config.yaml`)

```yaml
role: host
wake_word: compressor

# Trained openWakeWord model (see docs/WAKE-WORD-TRAINING.md). Falls back
# to cloud STT for wake detection until the model file exists here.
wake_model_path: models/compressor.onnx
wake_threshold: 0.5

anthropic_api_key: sk-ant-...

tuya:
  devices:
    - name: Living Room Light
      device_id: abc123def456
      local_key: xxxxxxxxxxxx
      ip: 192.168.1.50
      version: 3.3
      switch_dps: 20    # the DP index the power switch lives on. Bulbs use
                         # 20 (switch_led); plugs/outlets are typically 1
                         # (the default when switch_dps is omitted).

spotify:
  client_id: YOUR_SPOTIFY_CLIENT_ID
  client_secret: YOUR_SPOTIFY_CLIENT_SECRET
  redirect_uri: http://localhost:8888/callback

# Programs this machine can open by voice — see "Programs by voice" below.
programs:
  - name: brave
    launch: brave
    process_name: brave
    aliases: [browser]
    processes:
      youtube: https://youtube.com
```

`anthropic_api_key` is required on the Host and is host-only — Followers never need one.

### Follower config (`config.yaml`)

```yaml
role: follower
wake_word: compressor
wake_model_path: models/compressor.onnx
wake_threshold: 0.5
host_ip: 192.168.1.100    # LAN IP of the Host machine
host_port: 8765

unit_name: Kitchen         # required — identifies this unit to the Host and
                            # attributes host-side action-log entries to it

# Optional — programs this specific follower can open by voice. Each unit
# has its own list; a command spoken to a follower opens the program there.
programs:
  - name: notepad
    launch: notepad
    process_name: notepad
```

Followers do **not** need Tuya, Spotify, or an `anthropic_api_key` in their config — those run on the Host only. `unit_name` is required for every Follower and should be unique per unit. `wake_model_path`/`wake_threshold` are optional on every unit (host and followers alike); omit them to use the cloud-STT wake fallback.

---

## Getting Tuya Device Info

### Step 1 — Scan your network

Run this from the project root to discover all Tuya devices on your LAN (no cloud access required):

```bash
py scan_tuya.py
```

This outputs device IDs and IPs. Copy the snippet into your `config.yaml` and rename each device.

### Step 2 — Get local keys

Local keys are required to control devices and must come from the Tuya IoT portal:

1. Create an account at [iot.tuya.com](https://iot.tuya.com)
2. Go to **Cloud → Development** and create a project (region: Americas)
3. Under your project, go to the **Devices** tab
4. Click **"Link Tuya App Account"** → scan the QR code with your **Smart Life** or **Tuya Smart** app
5. Your devices will now appear in the portal
6. Click a device → **"..."** → **See device details** → copy the **Local Key**
7. Paste each key into the matching device entry in `config.yaml`

### Step 3 — Verify (optional)

Once local keys are in your config, you can verify with the tinytuya wizard:

```bash
py -m tinytuya wizard
```

---

## Spotify Setup

1. Go to [developer.spotify.com](https://developer.spotify.com) → Dashboard → Create app
2. Set the redirect URI to `http://localhost:8888/callback` (must match your config exactly)
3. Copy the **Client ID** and **Client Secret** into `config.yaml`
4. On first run, a browser window will open for OAuth login — authorize it once and the token is cached

---

## Programs by voice

Any unit (host or follower) can open programs on itself by voice — e.g.
"compressor, open Brave and go to YouTube". Add a `programs:` block to
that unit's `config.yaml`:

```yaml
programs:
  - name: brave
    launch: brave              # what gets passed to os.startfile()
    process_name: brave        # process name used to detect "already running"
    aliases: [browser]         # optional alternate names Compressor will match
    processes:                 # optional named sub-actions ("go to youtube")
      youtube: https://youtube.com
  - name: notepad
    launch: notepad
    process_name: notepad
```

A command spoken to a follower opens the program on that follower, not the
host — each unit only needs the `programs:` entries for what it can launch
locally. The first time you ask for a process that isn't listed under
`processes` (e.g. "open Brave and go to Reddit"), Compressor opens it and
remembers the mapping in that unit's `programs_learned.yaml`, so it doesn't
need to ask again next time. `programs_learned.yaml` is created automatically
and grows independently per unit. A wrong learned mapping persists (stored
mappings win over new guesses) — delete its line from that unit's
`programs_learned.yaml` to make the assistant re-learn it.

---

## Coding by voice (Claude mode)

Say **"Compressor" → "Start Claude"** (or "Start Claude in <project>") and
Compressor becomes a voice interface to a coding agent running on that
machine: everything you say goes straight to the agent as a prompt, and
its responses are spoken back.

Tasks run in the background — the microphone keeps listening while the
agent works, and the console streams what it's doing live (one
`[Claude] > <tool>: <target>` line per action), so you can watch the work
on screen while you talk. Speak again mid-task and the new request is
queued ("Queued.") and sent as soon as the current one finishes; each
finished task's response is spoken when it completes.

Say **"Compressor" alone** to exit — the wake word is the universal
escape hatch (embedded mentions of the word inside a sentence are passed
through to the agent). Exiting while a task is still running **cancels
it** and discards its result, so if you want the work to finish, stay in
the mode (silence is fine — a running task never idle-times-out the mode).

Configure it with the `coding_agent:` section (see `config.example.yaml`).
The layer is agent-agnostic — which agent and model run come from config;
currently `claude_code` is the only supported agent (requires the
[Claude Code](https://claude.com/claude-code) CLI installed and signed in).
Sessions run in the configured project directory with auto-approved
edits (`acceptEdits`) — `permission_mode: bypassPermissions` in config is
rejected and downgraded to `acceptEdits`. That said, a session still
inherits the target project's own Claude Code permission settings (e.g.
`.claude/settings.local.json` command allowlists), so review a project's
allowlists before pointing a hot microphone at it.

---

## Running

### Host

```bash
py main.py
```

The host starts its FastAPI server on port 8765, then waits for the wake word.

### Follower

```bash
py main.py
```

Same command. The `role: follower` in your config tells it to connect to the host instead of starting a server.

### Firewall (Windows)

The host needs port 8765 open for follower connections:

```powershell
netsh advfirewall firewall add rule name="Compressor" dir=in action=allow protocol=TCP localport=8765 remoteip=LocalSubnet
```

Note that this port is unauthenticated: any device on the local network can send
queries and commands (including opening programs) to the host. Only run this on
a trusted home LAN.

---

## Usage

Say the wake word to activate, then speak your command:

| Command | Example |
|---|---|
| Control a device | "Turn off the living room light" |
| Toggle a device | "Toggle the bedroom fan" |
| Play music | "Play Bohemian Rhapsody" |
| Play everywhere | "Play something chill on all speakers" |
| Pause | "Pause the music" |
| Skip | "Next song" |
| Volume | "Turn it up" / "Turn it down" |
| Open a program | "Open Brave" |
| Open a program to a specific page/action | "Open Brave and go to YouTube" |

Commands are always handled by the unit you spoke to — an "open a program" command opens it on that unit, not the host.

---

## Troubleshooting

**"Device not found"** — Check that the device name in your command loosely matches the name in `config.yaml`. Matching is fuzzy (substring).

**"Program isn't configured on \<unit\>"** — Add a `programs:` entry for it in that unit's `config.yaml` (see "Programs by voice" above). Each unit only knows the programs listed in its own config plus anything it has learned into `programs_learned.yaml`.

**Device says it turned on but nothing happened** — Wrong `switch_dps`. Tuya devices ACK the command and report success even when it targets the wrong data point, so this fails silently. Bulbs are usually `switch_dps: 20`; plugs/outlets are usually `1` (the default if you omit the field). See Step 2 below to confirm via the `tinytuya` wizard.

**Tuya error 1106 "permission deny"** — Your IoT project doesn't have the device linked. Follow Step 2 in the Tuya setup section above to link your Smart Life account.

**No Tuya devices found on scan** — Devices must be on the same subnet. Make sure they're powered on and your machine isn't on a guest network.

**Spotify "No devices found"** — Spotify must be open and active on at least one device before issuing a play command.

**Follower can't connect to host** — Confirm `host_ip` in the follower config matches the host's LAN IP (`ipconfig` on Windows). Check the firewall rule above.

**Wake word not detected** — Check that your microphone is set as the default input device in your OS audio settings. If you haven't trained a model yet (`wake_model_path` file doesn't exist), Compressor falls back to cloud STT for wake detection, which is slower and less reliable — see [docs/WAKE-WORD-TRAINING.md](docs/WAKE-WORD-TRAINING.md). If a model is trained but wakes are missed or too frequent, adjust `wake_threshold` (lower = more sensitive).
