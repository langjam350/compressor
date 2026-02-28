from typing import Callable
import anthropic

TOOLS = [
    {
        "name": "control_tuya_device",
        "description": "Turn a registered smart home IoT device on, off, or toggle its state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Human-readable name of the device, e.g. 'Living Room Light'"
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


class AIClient:
    def __init__(self, api_key: str, system_prompt: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._system = system_prompt

    def ask(self, query: str, tool_handler: Callable[[str, dict], str]) -> str:
        messages = [{"role": "user", "content": query}]

        while True:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self._system,
                tools=TOOLS,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = tool_handler(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "I couldn't generate a response."
