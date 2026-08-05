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
        "description": "Control Spotify music playback. Use house_speakers=true when the user says 'house speakers' or wants music everywhere.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "volume_up", "volume_down"],
                    "description": "Playback action"
                },
                "query": {
                    "type": "string",
                    "description": "Search term for the 'play' action, e.g. 'jazz', 'Radiohead', 'chill playlist'"
                },
                "house_speakers": {
                    "type": "boolean",
                    "description": "If true, play on all connected devices in the house"
                }
            },
            "required": ["action"]
        }
    }
]
