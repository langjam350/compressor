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
- Alexa-style music lookup — songs, artists, albums, and playlists on
  Spotify, with an automatic YouTube fallback when Spotify has no good
  match (plus configurable words that jump straight to a YouTube
  channel's newest upload)
- Starts and stops the Spotify app itself by voice, on the host and every
  follower at once — and auto-opens it when you ask for music and no
  Spotify device is running yet
- House-wide playback across units
- Opens programs by voice on whichever machine you spoke to
  ("compressor, open Brave and go to YouTube") — and learns new
  program actions the first time you use them
- Per-unit conversation isolation and a host-side action log of
  everything the system did

---

## Architecture

```
[Owner: Personal Desktop]  ←──── priority 1 in units.json
    │                             runs FastAPI server (port 8765)
    │                             handles AI, Tuya, Spotify, scheduled jobs
    │                             broadcasts commands to followers via WebSocket
    │
    └──── [Personal Laptop]  ←── priority 2: follows while the desktop is up,
    │                            takes over automatically when it goes down
    └──── [Follower machine] ←── listens for wake word, relays to the owner
```

Exactly one unit **owns** the system at a time. The owner runs the AI and integration logic and is the only machine that needs an Anthropic API key — followers hold zero Anthropic credentials. A follower captures a spoken command, sends it to the owner over `POST /query` (`{unit_name, text}` in, `{response}` out), and speaks back whatever comes home. Followers also stay connected over WebSocket so that "play everywhere" commands and targeted actions (like opening a program on a specific unit) can be broadcast to the right machine.

Which unit owns the system is **elected at runtime** from the tier list in `units.json`, not fixed in config — see [Ownership and failover](#ownership-and-failover).

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

### Unit tier list (`units.json`)

Every unit shares one `units.json`, listing every machine that may own the
system, best first. It holds no secrets and is committed to the repo — copy the
same file to every unit.

```json
{
  "units": [
    { "name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100", "host_port": 8765 },
    { "name": "Personal Laptop",  "priority": 2, "host_ip": "192.168.0.166", "host_port": 8765 }
  ]
}
```

Priorities must be unique. `host_ip` is each machine's LAN IP (`ipconfig` on
Windows). Start a unit with the name that matches its entry:

```bash
python main.py "Personal Laptop"
```

### Unit config (`config.yaml`)

```yaml
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
  redirect_uri: http://127.0.0.1:8888/callback

# Programs this machine can open by voice — see "Programs by voice" below.
programs:
  - name: brave
    launch: brave
    process_name: brave
    aliases: [browser]
    processes:
      youtube: https://youtube.com
```

`anthropic_api_key` decides whether a unit is **eligible to own the system**. A
unit without one can still listen and relay, but will never take over — so give
it to every machine you want in the failover chain, and leave it off the ones
you don't. Tuya and Spotify credentials only matter on a unit that may own the
system, for the same reason.

`programs` is per-unit: a command spoken to a machine opens the program on that
machine, so each one only needs entries for what it can actually launch.
`wake_model_path`/`wake_threshold` are optional everywhere; omit them to use the
cloud-STT wake fallback.

---

## Ownership and failover

The unit at priority 1 in `units.json` owns the system whenever it is online.
If it goes down, the next eligible unit takes over automatically, and hands
ownership back when the higher unit returns. Nothing needs to be reconfigured
and no unit needs restarting.

How it works: every unit runs the FastAPI server all the time and answers
`GET /health` with `{unit_name, owner, priority}`. On startup, and then every 15
seconds, a unit probes the units listed *ahead* of it. If one answers claiming
ownership, this unit follows it; if none do, this unit takes over.

- **Taking over** waits for two consecutive missed rounds (about 30 seconds), so
  a single dropped packet doesn't churn the host stack.
- **Standing down** happens on the first round that sees a higher unit return —
  yielding is always safe, so it isn't delayed.
- Both transitions are spoken aloud and recorded in `logs/actions.txt` as
  `ownership` events.

Because the tier list is a strict order that every unit reads identically, no
negotiation is needed — each machine reaches the same answer on its own.

Setting `role: host` or `role: follower` in `config.yaml` pins a unit and skips
the election entirely. Use that only for debugging or for a unit that must never
take over.

**Troubleshooting:** if two units both think they own the system for longer than
a minute, they can't reach each other — check `host_ip` in `units.json` against
`ipconfig` on each machine and confirm port 8765 is open through the firewall
(see below). If a unit refuses to start with "is not in the registry", the name
passed to `python main.py` doesn't match any `name` in `units.json`.

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
2. Set the redirect URI to `http://127.0.0.1:8888/callback` (must match your config exactly — Spotify no longer accepts `localhost` for new apps)
3. Copy the **Client ID** and **Client Secret** into `config.yaml`
4. On first run, a browser window will open for OAuth login — authorize it once and the token is cached

---

## Music: how playback is resolved

"Compressor, play ..." works like Alexa's lookup:

1. **Channel-default words first.** If the query contains a word listed
   under `youtube.channel_defaults` in the host's `config.yaml`, the most
   recent upload of that channel is played from YouTube — no search at
   all. Values are a channel URL or `@handle`.
2. **Spotify search.** Songs, artists, albums, and playlists are all
   searched and the best name-match wins — an artist match plays their
   catalog, an album match plays the album. Saying what you mean helps
   ("play the album ...", "play some Radiohead").
3. **YouTube fallback.** If Spotify's best match is poor (or you say
   "on YouTube"), the host looks the query up on YouTube via yt-dlp (no
   API key needed) and opens the result in the browser of the unit you
   spoke to — or every unit for "house speakers". This needs a program
   with the `browser` alias in that unit's `programs:` list.

The Spotify **application** itself is also voice-controllable:
"open Spotify" / "close Spotify" starts or stops the app on the host
**and every follower**. And when you ask for music while no Spotify
device is running, Compressor auto-opens the app everywhere and waits
(up to ~20s) for a device to appear before playing.

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

Every unit runs the same command — pass the machine's name from `units.json`:

```bash
py main.py "Personal Desktop"     # on the home machine
py main.py "Personal Laptop"      # on the laptop
```

Each unit starts its FastAPI server on port 8765, elects its role from the tier
list, prints who owns the system, then waits for the wake word. No per-machine
role setting is involved.

### Firewall (Windows)

Every unit needs port 8765 open — followers connect to the owner, and the owner
is probed by the units below it in the tier list:

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

**Follower can't connect to the owner** — Confirm each unit's `host_ip` in `units.json` matches that machine's LAN IP (`ipconfig` on Windows), and that `units.json` is identical on every unit. Check the firewall rule above.

**Wake word not detected** — Check that your microphone is set as the default input device in your OS audio settings. If you haven't trained a model yet (`wake_model_path` file doesn't exist), Compressor falls back to cloud STT for wake detection, which is slower and less reliable — see [docs/WAKE-WORD-TRAINING.md](docs/WAKE-WORD-TRAINING.md). If a model is trained but wakes are missed or too frequent, adjust `wake_threshold` (lower = more sensitive).
