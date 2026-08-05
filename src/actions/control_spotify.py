from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    if ctx.spotify is None:
        return "Integration not configured."
    house = tool_input.get("house_speakers", False)
    result = ctx.spotify.control(
        tool_input["action"],
        tool_input.get("query"),
        house_speakers=house,
    )
    if house and ctx.network is not None:
        ctx.network.broadcast({
            "type": "spotify",
            "action": tool_input["action"],
            "query": tool_input.get("query"),
        })
    return result
