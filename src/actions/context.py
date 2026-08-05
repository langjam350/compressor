from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ActionContext:
    """Everything an action may need, handed in by Assistant per tool call."""
    unit_name: str
    tuya: Any = None
    spotify: Any = None
    launcher: Any = None
    network: Any = None
    config: Optional[dict] = None
    host_unit_name: str = "host"
