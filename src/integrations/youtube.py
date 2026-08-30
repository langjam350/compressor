"""YouTube lookup via yt-dlp — no API key required.

Used as the fallback music source when Spotify has no good match (or the
user explicitly asks for YouTube), plus config-driven channel defaults:
words that map straight to a channel's most recent upload, e.g.

    youtube:
      channel_defaults:
        lofi: "@LofiGirl"
        sermon: "https://www.youtube.com/@SomeChurch"

Lookups only fetch metadata (flat extraction, nothing downloaded); the
resulting watch URL is opened in a browser on the target unit(s).

Never raises: every lookup returns a result dict or None.
"""
import re

try:
    import yt_dlp
except ImportError:  # optional dependency — YouTube fallback just disables
    yt_dlp = None

_FLAT_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
    "playlist_items": "1",
}


class YouTubeSearcher:
    def __init__(self, channel_defaults: dict[str, str] | None = None):
        # spoken word (lowercased) -> channel URL or @handle
        self._channel_defaults = {
            str(k).lower(): str(v) for k, v in (channel_defaults or {}).items()
        }

    @staticmethod
    def available() -> bool:
        return yt_dlp is not None

    # ------------------------------------------------------------------ #
    # Lookup                                                              #
    # ------------------------------------------------------------------ #

    def _extract_first(self, target: str) -> dict | None:
        """Flat-extract `target` and return the first video as
        {title, url, channel}, or None."""
        if yt_dlp is None:
            return None
        try:
            with yt_dlp.YoutubeDL(dict(_FLAT_OPTS)) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception as e:
            print(f"[YouTube] Lookup failed for {target!r}: {e}")
            return None
        if not info:
            return None

        entry = None
        entries = info.get("entries")
        if entries is not None:
            for candidate in entries:  # may be a generator under extract_flat
                if candidate:
                    entry = candidate
                    break
        elif info.get("id"):
            entry = info
        if not entry:
            return None

        video_id = entry.get("id")
        url = entry.get("url")
        # Flat channel/search entries sometimes carry non-watch URLs; the
        # video id is the reliable thing to build the watch URL from.
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            return None
        return {
            "title": entry.get("title") or "a video",
            "url": url,
            "channel": entry.get("channel") or entry.get("uploader") or "",
        }

    @staticmethod
    def _channel_videos_url(channel: str) -> str:
        c = channel.strip()
        if c.startswith(("http://", "https://")):
            base = c.rstrip("/")
            return base if base.endswith("/videos") else base + "/videos"
        if not c.startswith("@"):
            c = "@" + c.replace(" ", "")
        return f"https://www.youtube.com/{c}/videos"

    def latest_upload(self, channel: str) -> dict | None:
        """Most recent upload on a channel (URL or @handle)."""
        return self._extract_first(self._channel_videos_url(channel))

    def search(self, query: str) -> dict | None:
        return self._extract_first(f"ytsearch1:{query}")

    def channel_for(self, query: str) -> str | None:
        """The configured default channel whose trigger word appears in
        the query, or None."""
        q = query.lower()
        for word, channel in self._channel_defaults.items():
            if re.search(rf"\b{re.escape(word)}\b", q):
                return channel
        return None

    def resolve(self, query: str) -> dict | None:
        """Channel-default word -> that channel's newest upload; otherwise
        a plain search. Falls back to search if the channel lookup fails."""
        channel = self.channel_for(query)
        if channel:
            result = self.latest_upload(channel)
            if result:
                return result
        return self.search(query)
