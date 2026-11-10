"""Sends text into a running WezTerm tab, identified by its tab title.

Used to deliver a delayed instruction to an interactive agent (e.g. a Claude
Code session) the user already has open in a terminal tab — not to launch
one. Requires the `wezterm` CLI on PATH and a running WezTerm instance;
absent-tolerant like every other integration.
"""
import json
import shutil
import subprocess


def _list_panes() -> list[dict]:
    cli = shutil.which("wezterm")
    if cli is None:
        raise RuntimeError("wezterm isn't installed or not on PATH.")
    result = subprocess.run(
        [cli, "cli", "list", "--format", "json"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "wezterm cli list failed.")
    return json.loads(result.stdout or "[]")


def find_pane_by_tab_title(title: str) -> int | None:
    """Return the pane id of the active pane in the tab whose title matches
    (case-insensitive), or None if no tab, or more than one tab, matches."""
    panes = _list_panes()
    key = title.strip().lower()
    matches = [
        p for p in panes
        if (p.get("tab_title") or p.get("title") or "").strip().lower() == key
    ]
    if not matches:
        return None
    active = [p for p in matches if p.get("is_active")]
    chosen = active[0] if active else matches[0]
    return chosen.get("pane_id")


def send_to_tab(tab_name: str, message: str) -> str:
    """Type `message` into the named WezTerm tab and press Enter. Never raises."""
    try:
        pane_id = find_pane_by_tab_title(tab_name)
    except Exception as e:
        return f"Couldn't reach WezTerm: {e}"

    if pane_id is None:
        return f"No WezTerm tab named '{tab_name}' found."

    cli = shutil.which("wezterm")
    try:
        subprocess.run(
            [cli, "cli", "send-text", "--pane-id", str(pane_id), "--no-paste", message + "\r"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except Exception as e:
        return f"Failed to send message to '{tab_name}': {e}"

    return f"Sent message to '{tab_name}'."
