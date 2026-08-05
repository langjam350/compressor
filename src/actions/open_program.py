from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    program = tool_input["program"]
    process = tool_input.get("process")
    argument = tool_input.get("argument")

    if ctx.unit_name == ctx.host_unit_name:
        if ctx.launcher is None:
            return "Program launching isn't configured on this machine."
        return ctx.launcher.open(program, process=process, argument=argument)

    # Requester is a follower: fire-and-forget targeted broadcast. The
    # spoken response is optimistic — a failed launch is only visible in
    # the follower's own log (known v1 limitation, see design spec).
    if ctx.network is None:
        return "Program launching isn't configured for remote units."
    ctx.network.broadcast({
        "type": "open_program",
        "target_unit": ctx.unit_name,
        "program": program,
        "process": process,
        "argument": argument,
    })
    return f"Opening {process or program} on {ctx.unit_name}."
