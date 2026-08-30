"""Start/stop the Spotify desktop application on THIS machine.

Separate from SpotifyController (the Spotify Web API client): these are
OS-level operations that need no credentials, so they work on any unit —
host or follower — and are what the "spotify_app" network broadcast runs
on every machine in the house.

Never raises: every path returns a human-sensible result string (same
defensive contract as TuyaController and ProgramLauncher).
"""
import os

import psutil

_PROCESS_NAME = "spotify.exe"

# The spotify: URI protocol is registered by both the desktop and the
# Microsoft Store install, so launching through it works for either.
_LAUNCH_URI = "spotify:"


def is_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() == _PROCESS_NAME:
            return True
    return False


def start() -> str:
    if is_running():
        return "Spotify is already running."
    try:
        os.startfile(_LAUNCH_URI)
        return "Starting Spotify."
    except Exception as e:
        return f"Couldn't start Spotify ({e})."


def stop() -> str:
    stopped = 0
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() == _PROCESS_NAME:
            try:
                proc.terminate()
                stopped += 1
            except Exception:
                pass
    return "Spotify closed." if stopped else "Spotify isn't running."
