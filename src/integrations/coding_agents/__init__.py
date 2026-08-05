"""Agent-agnostic coding-agent sessions.

The voice mode talks only to the CodingAgentSession interface; which
agent (and model) actually runs comes from config.yaml's coding_agent
section. v1 ships exactly one backend: Claude Code.
"""
from typing import Protocol


class CodingAgentSession(Protocol):
    def start(self, workdir: str) -> None: ...
    def send(self, text: str) -> str: ...
    def stop(self) -> None: ...


class _UnsupportedSession:
    """Stub returned for agents that have no backend yet."""

    def __init__(self, agent_name: str):
        self._agent_name = agent_name

    def start(self, workdir: str) -> None:
        pass

    def send(self, text: str) -> str:
        return f"Coding agent '{self._agent_name}' isn't supported on this unit."

    def stop(self) -> None:
        pass


def create_session(agent_config: dict) -> CodingAgentSession:
    """Build a session for the configured agent. Parameters come from config, not code."""
    agent = (agent_config.get("agent") or "claude_code").lower()
    if agent == "claude_code":
        from src.integrations.coding_agents.claude_code import ClaudeCodeSession
        return ClaudeCodeSession(
            model=agent_config.get("model"),
            permission_mode=agent_config.get("permission_mode", "acceptEdits"),
            max_turns=int(agent_config.get("max_turns", 25)),
            task_timeout_seconds=int(agent_config.get("task_timeout_seconds", 600)),
        )
    return _UnsupportedSession(agent)
