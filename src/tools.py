TOOLS = [
    {
        "name": "control_tuya_device",
        "description": (
            "Turn a registered smart home IoT device on, off, or toggle its state. "
            "device_name can be a specific device name (e.g. 'Living Room Light') "
            "OR a category such as 'lights', 'bedroom lights', 'fans', or 'all'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Human-readable name or category of the device(s), e.g. 'Living Room Light', 'lights', 'bedroom lights'"
                },
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "toggle"],
                    "description": "Action to perform"
                }
            },
            "required": ["device_name", "action"]
        }
    },
    {
        "name": "control_spotify",
        "description": (
            "Play and control music. 'play' with a query searches Spotify for songs, artists, "
            "albums, or playlists and automatically falls back to YouTube when Spotify has no "
            "good match (set source='youtube' if the user explicitly asks for YouTube). "
            "'start_app'/'stop_app' open or close the Spotify application itself on every "
            "machine in the house ('open Spotify', 'close Spotify'). Use house_speakers=true "
            "when the user says 'house speakers' or wants music everywhere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "volume_up", "volume_down", "start_app", "stop_app"],
                    "description": "Playback action, or start_app/stop_app to open/close the Spotify application"
                },
                "query": {
                    "type": "string",
                    "description": "Search term for the 'play' action, e.g. 'jazz', 'Radiohead', 'chill playlist'"
                },
                "query_type": {
                    "type": "string",
                    "enum": ["song", "artist", "album", "playlist", "auto"],
                    "description": "What kind of thing the user asked for, when their phrasing makes it clear ('play the song ...', 'play some Radiohead' = artist, 'put on the album ...'). Use 'auto' when unsure."
                },
                "source": {
                    "type": "string",
                    "enum": ["auto", "spotify", "youtube"],
                    "description": "Music source. 'auto' (default) tries Spotify first with YouTube fallback; use 'youtube' or 'spotify' only when the user names the service."
                },
                "house_speakers": {
                    "type": "boolean",
                    "description": "If true, play on all connected devices in the house"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "open_program",
        "description": (
            "Open a program/application on the computer in the room where the user spoke. "
            "Programs available on the host are listed in the system prompt (other units have "
            "their own lists — attempt the call even for a program not listed). When the user "
            "wants something done inside the program (a website, a file), also give a short "
            "lowercase 'process' name AND your best-guess 'argument' — e.g. going to YouTube "
            "in a browser is process 'youtube' with argument 'https://youtube.com'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "program": {
                    "type": "string",
                    "description": "Program to open, e.g. 'brave', 'notepad'. 'browser' maps to the user's preferred browser."
                },
                "process": {
                    "type": "string",
                    "description": "Short lowercase name for the action inside the program, e.g. 'youtube'"
                },
                "argument": {
                    "type": "string",
                    "description": "Concrete URL, file path, or command-line argument for the process, e.g. 'https://youtube.com'"
                }
            },
            "required": ["program"]
        }
    },
    {
        "name": "scan_network",
        "description": (
            "Scan the local network for smart home devices and update the ones that were "
            "unreachable because their IP address was missing or had changed. Use this when "
            "the user asks to scan the network, find their devices, or when a device control "
            "attempt reported it couldn't find a device's IP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "message_wezterm_tab",
        "description": (
            "Schedule a text message to be typed (and submitted with Enter) into a named "
            "WezTerm terminal tab at a specific clock time today. Most often used to send "
            "a delayed instruction to a Claude Code agent already running in that tab, e.g. "
            "to resume work once a usage limit refreshes. If the given time already passed "
            "today, it fires tomorrow at that time instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_name": {
                    "type": "string",
                    "description": "The WezTerm tab's title, exactly as it appears in the tab bar."
                },
                "message": {
                    "type": "string",
                    "description": "The text to type into the tab and submit with Enter."
                },
                "hour": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 23,
                    "description": "Hour of day to send, 24-hour clock."
                },
                "minute": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Minute of the hour to send (default 0)."
                },
                "unit": {
                    "type": "string",
                    "description": "Which unit's machine the WezTerm tab is on, e.g. 'Personal Laptop'. Defaults to the unit being spoken to."
                }
            },
            "required": ["tab_name", "message", "hour"]
        }
    },
]
