from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ActionContext:
    """Everything an action may need, handed in by Assistant per tool call."""
    unit_name: str
    tuya: Any = None
    spotify: Any = None
    youtube: Any = None
    launcher: Any = None
    network: Any = None
    config: Optional[dict] = None
    host_unit_name: str = "host"
    tuya_reload: Optional[Callable[[list], None]] = None
    known_units: Optional[list] = None
    schedule_wezterm_send: Optional[Callable[[dict], None]] = None
