import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)


class SpotifyController:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
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

    def control(self, action: str, query: str = None, house_speakers: bool = False) -> str:
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
            device_ids = self._get_device_ids(house_speakers)
            if not device_ids:
                return "No Spotify devices found. Make sure Spotify is open on at least one device."

            if query:
                results = self._sp.search(q=query, limit=1, type="track")
                tracks = results.get("tracks", {}).get("items", [])
                if not tracks:
                    return f"No results found for '{query}'."
                track = tracks[0]
                uri = track["uri"]
                name = track["name"]
                artist = track["artists"][0]["name"]
                for did in device_ids:
                    self._sp.start_playback(device_id=did, uris=[uri])
                speaker_msg = " on all house speakers" if house_speakers else ""
                return f"Playing {name} by {artist}{speaker_msg}."
            else:
                for did in device_ids:
                    self._sp.start_playback(device_id=did)
                return "Resuming playback."

        return "Unknown Spotify command."
