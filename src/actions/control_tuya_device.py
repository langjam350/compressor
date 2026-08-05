from src.actions.context import ActionContext


def run(ctx: ActionContext, tool_input: dict) -> str:
    if ctx.tuya is None:
        return "Integration not configured."
    return ctx.tuya.control(tool_input["device_name"], tool_input["action"])
