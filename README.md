# Condensor

A voice-activated home assistant that controls smart devices and Spotify across multiple machines on your LAN. Say the wake word, give a command — Condensor handles the rest.

**Features**
- Wake-word activation ("condensor" by default)
- Natural language via Claude AI
- Tuya smart device control (lights, plugs, fans, etc.)
- Spotify playback control, including house-wide speaker sync
- Multi-room support: one Host machine, unlimited Client machines

---

## Architecture

```
[Host machine]  ←──── runs FastAPI server (port 8765)
    │                  handles AI, Tuya, Spotify
    │                  broadcasts commands to clients via WebSocket
    │
    └──── [Client machine]  ←── listens for wake word
    └──── [Client machine]  ←── plays back Spotify on local device
```

The **Host** runs the AI and integration logic. **Clients** connect to it over WebSocket and receive playback commands so that "play everywhere" works across all speakers in the house.

---

## Requirements

- Python 3.11+
- Microphone on each machine running Condensor
- All machines on the same LAN
- [Anthropic API key](https://console.anthropic.com)
- Tuya IoT account (for smart device control)
- Spotify Developer app (for music control)

---

## Installation

Run this on **every machine** (host and clients):

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
wake_word: condensor

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

### Client config (`config.yaml`)

```yaml
role: client
wake_word: condensor
host_ip: 192.168.1.100    # LAN IP of the Host machine
host_port: 8765

anthropic_api_key: sk-ant-...
```

Clients do **not** need Tuya or Spotify config — those run on the Host only.

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

### Client

```bash
py main.py
```

Same command. The `role: client` in your config tells it to connect to the host instead of starting a server.

### Firewall (Windows)

The host needs port 8765 open for client connections:

```powershell
netsh advfirewall firewall add rule name="Condensor" dir=in action=allow protocol=TCP localport=8765
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

**Client can't connect to host** — Confirm `host_ip` in the client config matches the host's LAN IP (`ipconfig` on Windows). Check the firewall rule above.

**Wake word not detected** — Check that your microphone is set as the default input device in your OS audio settings.
