# Compressor

A voice-activated home assistant that controls smart devices and Spotify across multiple machines on your LAN. Say the wake word, give a command — Compressor handles the rest.

**Features**
- Wake-word activation ("compressor" by default)
- Natural language via Claude AI
- Tuya smart device control (lights, plugs, fans, etc.)
- Spotify playback control, including house-wide speaker sync
- Multi-room support: one Host machine, unlimited Follower machines

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

The **Host** runs the AI and integration logic and is the only machine that needs an Anthropic API key — **Followers** hold zero Anthropic credentials. A Follower captures a spoken command, sends it to the Host over `POST /query` (`{unit_name, text}` in, `{response}` out), and speaks back whatever the Host returns. Followers also stay connected to the Host over WebSocket so that "play everywhere" commands can be broadcast to every speaker in the house.

Note: the Host keeps each unit's conversation history in memory only. Restarting the Host clears all in-progress conversation context for every unit — a follow-up like "what about the bedroom?" won't be understood as a continuation after a Host restart.

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

anthropic_api_key: sk-ant-...

tuya:
  devices:
    - name: Living Room Light
      device_id: abc123def456
      local_key: xxxxxxxxxxxx
      ip: 192.168.1.50
      version: 3.3

spotify:
  client_id: YOUR_SPOTIFY_CLIENT_ID
  client_secret: YOUR_SPOTIFY_CLIENT_SECRET
  redirect_uri: http://localhost:8888/callback
```

`anthropic_api_key` is required on the Host and is host-only — Followers never need one.

### Follower config (`config.yaml`)

```yaml
role: follower
wake_word: compressor
host_ip: 192.168.1.100    # LAN IP of the Host machine
host_port: 8765

unit_name: Kitchen         # required — identifies this unit to the Host and
                            # attributes host-side action-log entries to it
```

Followers do **not** need Tuya, Spotify, or an `anthropic_api_key` in their config — those run on the Host only. `unit_name` is required for every Follower and should be unique per unit.

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
netsh advfirewall firewall add rule name="Compressor" dir=in action=allow protocol=TCP localport=8765
```

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

---

## Troubleshooting

**"Device not found"** — Check that the device name in your command loosely matches the name in `config.yaml`. Matching is fuzzy (substring).

**Tuya error 1106 "permission deny"** — Your IoT project doesn't have the device linked. Follow Step 2 in the Tuya setup section above to link your Smart Life account.

**No Tuya devices found on scan** — Devices must be on the same subnet. Make sure they're powered on and your machine isn't on a guest network.

**Spotify "No devices found"** — Spotify must be open and active on at least one device before issuing a play command.

**Follower can't connect to host** — Confirm `host_ip` in the follower config matches the host's LAN IP (`ipconfig` on Windows). Check the firewall rule above.

**Wake word not detected** — Check that your microphone is set as the default input device in your OS audio settings.
