import time
from difflib import SequenceMatcher
from typing import Callable, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)

# Below this search_best score, a match is considered "not great" and the
# action layer is free to fall back to YouTube instead.
GOOD_MATCH_THRESHOLD = 0.60

# How long to wait for a Spotify Connect device to appear after asking
# app_starter to open the Spotify app, and how often to re-check.
_APP_START_WAIT_SECONDS = 20
_APP_START_POLL_SECONDS = 2

# spoken query_type -> Spotify search type
_KIND_MAP = {
    "song": "track",
    "track": "track",
    "artist": "artist",
    "album": "album",
    "playlist": "playlist",
}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class SpotifyController:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        app_starter: Optional[Callable[[], None]] = None,
    ):
        # app_starter opens the Spotify app (locally and/or house-wide);
        # it's invoked when playback is requested but no Connect device
        # exists yet, then devices are polled until one shows up.
        self._app_starter = app_starter
        self._sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=SCOPE,
                open_browser=True,
            )
        )

    def _get_device_ids(self, house_speakers: bool) -> list[str]:
        devices = self._sp.devices().get("devices", [])
        if not devices:
            return []
        if house_speakers:
            return [d["id"] for d in devices]
        active = [d for d in devices if d["is_active"]]
        return [active[0]["id"]] if active else [devices[0]["id"]]

    def _wait_for_devices(self, house_speakers: bool) -> list[str]:
        """No Connect device yet: ask app_starter to open the Spotify app,
        then poll until a device registers (the app takes a few seconds to
        show up as a Connect device after launch)."""
        if self._app_starter is None:
            return []
        try:
            self._app_starter()
        except Exception as e:
            print(f"[Spotify] app_starter failed: {e}")
            return []
        deadline = time.time() + _APP_START_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(_APP_START_POLL_SECONDS)
            device_ids = self._get_device_ids(house_speakers)
            if device_ids:
                return device_ids
        return []

    # ------------------------------------------------------------------ #
    # Search                                                              #
    # ------------------------------------------------------------------ #

    def search_best(self, query: str, query_type: str = "auto") -> dict | None:
        """Alexa-style lookup: search tracks, artists, and albums (or just
        the kind the user named) and return the best match as
        {uri, kind, name, artist, score}, or None.

        score is mostly name similarity to the spoken query (popularity is
        a small tie-breaker), so the caller can judge whether the match is
        good enough or a YouTube fallback is warranted.
        """
        kind = _KIND_MAP.get((query_type or "auto").strip().lower())
        types = [kind] if kind else ["track", "artist", "album"]
        try:
            results = self._sp.search(q=query, limit=5, type=",".join(types))
        except Exception as e:
            print(f"[Spotify] Search failed: {e}")
            return None

        best = None
        for t in types:
            items = ((results.get(t + "s") or {}).get("items")) or []
            for item in items:
                if not item:
                    continue
                name = item.get("name", "")
                if t == "artist":
                    artist = ""
                else:
                    artists = item.get("artists") or []
                    artist = artists[0].get("name", "") if artists else ""
                score = _similarity(query, name)
                if artist:
                    # Spoken queries often include the artist ("kind of blue
                    # miles davis") — score against those forms too.
                    score = max(
                        score,
                        _similarity(query, f"{name} {artist}"),
                        _similarity(query, f"{artist} {name}"),
                    )
                score += (item.get("popularity") or 0) / 1000.0
                if best is None or score > best["score"]:
                    best = {
                        "uri": item["uri"],
                        "kind": t,
                        "name": name,
                        "artist": artist,
                        "score": score,
                    }
        return best

    # ------------------------------------------------------------------ #
    # Playback                                                            #
    # ------------------------------------------------------------------ #

    def play_item(self, item: dict, house_speakers: bool = False) -> str:
        """Start playing a search_best result — a single track by URI, or
        an artist/album/playlist as a playback context."""
        device_ids = self._get_device_ids(house_speakers)
        if not device_ids:
            device_ids = self._wait_for_devices(house_speakers)
        if not device_ids:
            return "No Spotify devices found. Make sure Spotify is open on at least one device."

        for did in device_ids:
            if item["kind"] == "track":
                self._sp.start_playback(device_id=did, uris=[item["uri"]])
            else:
                self._sp.start_playback(device_id=did, context_uri=item["uri"])

        speaker_msg = " on all house speakers" if house_speakers else ""
        if item["kind"] == "artist":
            return f"Playing songs by {item['name']}{speaker_msg}."
        label = {"album": "the album ", "playlist": "the playlist "}.get(item["kind"], "")
        by = f" by {item['artist']}" if item.get("artist") else ""
        return f"Playing {label}{item['name']}{by}{speaker_msg}."

    def control(
        self,
        action: str,
        query: str = None,
        house_speakers: bool = False,
        query_type: str = "auto",
    ) -> str:
        if action == "pause":
            self._sp.pause_playback()
            return "Playback paused."

        if action == "next":
            self._sp.next_track()
            return "Skipped to next track."

        if action == "previous":
            self._sp.previous_track()
            return "Playing previous track."

        if action == "volume_up":
            current = self._sp.current_playback()
            vol = min(100, current["device"]["volume_percent"] + 10)
            self._sp.volume(vol)
            return f"Volume at {vol}%."

        if action == "volume_down":
            current = self._sp.current_playback()
            vol = max(0, current["device"]["volume_percent"] - 10)
            self._sp.volume(vol)
            return f"Volume at {vol}%."

        if action == "play":
            if query:
                item = self.search_best(query, query_type)
                if item is None:
                    return f"No results found for '{query}'."
                return self.play_item(item, house_speakers=house_speakers)

            device_ids = self._get_device_ids(house_speakers)
            if not device_ids:
                device_ids = self._wait_for_devices(house_speakers)
            if not device_ids:
                return "No Spotify devices found. Make sure Spotify is open on at least one device."
            for did in device_ids:
                self._sp.start_playback(device_id=did)
            return "Resuming playback."

        return "Unknown Spotify command."
