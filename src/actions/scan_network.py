from pathlib import Path

import yaml

import scan_tuya
from src.actions.context import ActionContext

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def run(ctx: ActionContext, tool_input: dict) -> str:
    if ctx.tuya is None:
        return "Integration not configured."

    found = scan_tuya.scan_devices(timeout_retries=8)
    if not found:
        return "No devices found on the network."

    config_yaml = _PROJECT_ROOT / "config.yaml"
    if not config_yaml.exists():
        return "No devices found on the network."

    with open(config_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # tinytuya keys UDP scan results by IP; gwId is the device_id our config
    # entries are matched on.
    found_by_id = {info["gwId"]: (ip, info) for ip, info in found.items() if info.get("gwId")}
    devices = config.setdefault("tuya", {}).setdefault("devices", [])

    matched = []
    changed = False
    for entry in devices:
        match = found_by_id.get(entry.get("device_id"))
        if not match:
            continue
        matched.append(entry["name"])

        ip, info = match
        if entry.get("ip") != ip:
            entry["ip"] = ip
            changed = True

        version = info.get("version")
        if version:
            try:
                version = float(version)
            except (ValueError, TypeError):
                version = None
        if version and entry.get("version") != version:
            entry["version"] = version
            changed = True

    if not matched:
        return f"Found {len(found)} device(s) on the network, but none matched your configured devices."

    if changed:
        with open(config_yaml, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        if ctx.tuya_reload:
            ctx.tuya_reload(devices)

    names = matched[0] if len(matched) == 1 else ", ".join(matched[:-1]) + f" and {matched[-1]}"
    if changed:
        return f"Found {names} on the network. Ready to control now."
    return f"Found {names} on the network. Already up to date."
