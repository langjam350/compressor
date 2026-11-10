from datetime import datetime, timedelta

from src.actions.context import ActionContext


def _compute_fire_at(hour: int, minute: int, now: datetime | None = None) -> tuple[datetime, bool]:
    """Return (fire_at, rolled_to_tomorrow) for the next occurrence of hour:minute."""
    now = now or datetime.now()
    fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    tomorrow = fire_at <= now
    if tomorrow:
        fire_at += timedelta(days=1)
    return fire_at, tomorrow


def run(ctx: ActionContext, tool_input: dict) -> str:
    tab_name = tool_input["tab_name"]
    message = tool_input["message"]
    hour = tool_input["hour"]
    minute = tool_input.get("minute", 0)
    unit = tool_input.get("unit") or ctx.unit_name

    if ctx.known_units and unit not in ctx.known_units:
        return f"No unit named '{unit}' in your setup."

    fire_at, tomorrow = _compute_fire_at(hour, minute)

    payload = {
        "type": "schedule_wezterm_send",
        "target_unit": unit,
        "tab_name": tab_name,
        "message": message,
        "fire_at": fire_at.isoformat(),
    }

    # The host never receives its own broadcasts (see the dead Spotify
    # broadcast branch in _handle_network_command for the same trap) — run
    # locally instead when the target is this machine.
    if unit == ctx.host_unit_name:
        if ctx.schedule_wezterm_send:
            ctx.schedule_wezterm_send(payload)
    elif ctx.network:
        ctx.network.broadcast(payload)

    when = fire_at.strftime("%I:%M %p").lstrip("0")
    day = " tomorrow" if tomorrow else ""
    return f"Okay, I'll message the '{tab_name}' tab{day} at {when}."
