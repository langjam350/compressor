from concurrent.futures import ThreadPoolExecutor

import tinytuya

# Tight limits: tinytuya's defaults (5s timeout x 5 retries + 5s delays) block
# for ~45s per unreachable device, and an empty address triggers an 18s UDP
# discovery scan that raises if the device isn't found.
_CONNECTION_TIMEOUT = 3
_CONNECTION_RETRY_LIMIT = 1
_MAX_PARALLEL = 8

# Maps spoken category terms to the keywords that identify matching devices.
_CATEGORY_EXPANSION: dict[str, list[str]] = {
    "lights": ["light", "lamp", "bulb"],
    "light":  ["light", "lamp", "bulb"],
    "lamps":  ["lamp"],
    "lamp":   ["lamp"],
    "bulbs":  ["bulb"],
    "bulb":   ["bulb"],
    "fans":   ["fan"],
    "fan":    ["fan"],
}


class TuyaController:
    def __init__(self, devices: list[dict]):
        # devices: list of {name, device_id, local_key, ip, version}
        self._devices = {d["name"].lower(): d for d in devices}

    def _find_devices_by_category(self, category: str) -> list[dict]:
        """Return all devices that match a category string such as 'lights' or 'bedroom lights'."""
        if category.strip().lower() == "all":
            return list(self._devices.values())
        terms = category.lower().split()
        return [
            dev for name, dev in self._devices.items()
            if all(
                any(exp in name for exp in _CATEGORY_EXPANSION.get(term, [term]))
                for term in terms
            )
        ]

    def _control_single(self, dev: dict, action: str) -> str:
        device = tinytuya.OutletDevice(
            dev_id=dev["device_id"],
            address=dev["ip"],
            local_key=dev["local_key"],
            version=dev.get("version", 3.3),
            connection_timeout=_CONNECTION_TIMEOUT,
            connection_retry_limit=_CONNECTION_RETRY_LIMIT,
        )
        if action == "on":
            device.turn_on()
        elif action == "off":
            device.turn_off()
        elif action == "toggle":
            status = device.status()
            is_on = status.get("dps", {}).get("1", False)
            device.turn_off() if is_on else device.turn_on()
        return f"{dev['name']} turned {action}."

    def _safe_control(self, dev: dict, action: str) -> str:
        """Control one device, converting unusable config or errors into a report string."""
        if not dev.get("ip"):
            return f"{dev['name']} skipped (no IP — run the network scan to find it)."
        if not dev.get("local_key"):
            return f"{dev['name']} skipped (no local key — run the Tuya sync)."
        try:
            return self._control_single(dev, action)
        except Exception as e:
            return f"{dev['name']} failed ({e})."

    def control(self, device_name: str, action: str) -> str:
        # 1. Exact name match
        key = device_name.lower()
        if key in self._devices:
            return self._safe_control(self._devices[key], action)

        # 2. Category match ("lights", "bedroom lights", "fans", "all", …)
        devices = self._find_devices_by_category(device_name)
        if devices:
            with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(devices))) as pool:
                results = list(pool.map(lambda d: self._safe_control(d, action), devices))
            return f"Controlled {len(devices)} device(s): " + "; ".join(results)

        # 3. Fuzzy name match (substring fallback)
        for dev_key, dev in self._devices.items():
            if key in dev_key or dev_key in key:
                return self._safe_control(dev, action)

        return f"Device '{device_name}' not found. Check your config.yaml device list."
