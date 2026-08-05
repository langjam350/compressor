from typing import Callable
import anthropic


class AIClient:
    def __init__(self, api_key: str, system_prompt: str, tools: list[dict] | None = None):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._system = system_prompt
        self._tools = tools or []
        self._messages: list[dict] = []

    def reset(self) -> None:
        """Clear conversation history to start a new thread."""
        self._messages = []

    def ask(self, query: str, tool_handler: Callable[[str, dict], str]) -> str:
        self._messages.append({"role": "user", "content": query})

        while True:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self._system,
                tools=self._tools,
                messages=list(self._messages),
            )

            print(f"[AI] stop_reason={response.stop_reason}")
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
                self._messages.append({"role": "assistant", "content": response.content})
                self._messages.append({"role": "user", "content": tool_results})
            else:
                self._messages.append({"role": "assistant", "content": response.content})
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "I couldn't generate a response."
