from src.actions.context import ActionContext
from src.integrations import spotify_app
from src.integrations.spotify import GOOD_MATCH_THRESHOLD


def _play_youtube(ctx: ActionContext, result: dict, house_speakers: bool) -> str:
    """Open a YouTube result in the browser on the requesting unit — or on
    every unit for house-wide playback."""
    url = result["url"]
    title = result.get("title") or "a video"

    if house_speakers:
        if ctx.launcher is not None:
            ctx.launcher.open("browser", argument=url)
        if ctx.network is not None:
            ctx.network.broadcast({"type": "open_url", "target_unit": None, "url": url})
        return f"Playing {title} from YouTube everywhere."

    if ctx.unit_name == ctx.host_unit_name:
        if ctx.launcher is None:
            return f"I found {title} on YouTube but no browser is configured to play it."
        opened = ctx.launcher.open("browser", argument=url)
        if "isn't configured" in opened or opened.startswith("Couldn't"):
            return f"I found {title} on YouTube but couldn't open a browser: {opened}"
        return f"Playing {title} from YouTube."

    # Requester is a follower: fire-and-forget targeted broadcast, same
    # optimistic contract as open_program.
    if ctx.network is None:
        return f"I found {title} on YouTube but can't reach {ctx.unit_name} to play it."
    ctx.network.broadcast({"type": "open_url", "target_unit": ctx.unit_name, "url": url})
    return f"Playing {title} from YouTube on {ctx.unit_name}."


def run(ctx: ActionContext, tool_input: dict) -> str:
    action = tool_input["action"]
    house = tool_input.get("house_speakers", False)
    query = tool_input.get("query")
    query_type = tool_input.get("query_type", "auto")
    source = tool_input.get("source", "auto")

    # App start/stop is OS-level (no Spotify credentials needed): run it
    # locally on the host, then mirror on every follower.
    if action in ("start_app", "stop_app"):
        app_action = "start" if action == "start_app" else "stop"
        local_result = spotify_app.start() if action == "start_app" else spotify_app.stop()
        if ctx.network is not None:
            ctx.network.broadcast({"type": "spotify_app", "action": app_action})
            verb = "Starting" if action == "start_app" else "Closing"
            return f"{verb} Spotify on every unit."
        return local_result

    if action == "play" and query:
        # Channel-default words and explicit YouTube requests skip Spotify.
        forced_channel = ctx.youtube.channel_for(query) if ctx.youtube else None
        if forced_channel or source == "youtube":
            if ctx.youtube is None:
                return "YouTube isn't available on this host."
            yt = ctx.youtube.resolve(query)
            if yt is None:
                return f"No YouTube results found for '{query}'."
            return _play_youtube(ctx, yt, house)

        if ctx.spotify is None:
            if source != "spotify" and ctx.youtube is not None:
                yt = ctx.youtube.resolve(query)
                if yt is not None:
                    return _play_youtube(ctx, yt, house)
            return "Integration not configured."

        match = ctx.spotify.search_best(query, query_type)
        good = match is not None and match["score"] >= GOOD_MATCH_THRESHOLD
        if not good and source != "spotify" and ctx.youtube is not None:
            yt = ctx.youtube.resolve(query)
            if yt is not None:
                return _play_youtube(ctx, yt, house)
        if match is None:
            return f"No results found for '{query}'."
        # A mediocre Spotify match still beats nothing when YouTube also
        # came up empty (or was excluded).
        result = ctx.spotify.play_item(match, house_speakers=house)
    else:
        if ctx.spotify is None:
            return "Integration not configured."
        result = ctx.spotify.control(action, query, house_speakers=house, query_type=query_type)

    if house and ctx.network is not None:
        ctx.network.broadcast({
            "type": "spotify",
            "action": action,
            "query": query,
        })
    return result
