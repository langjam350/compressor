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


def _payload_error(payload) -> str | None:
    """tinytuya returns error payloads instead of raising on many failures."""
    if isinstance(payload, dict) and payload.get("Error"):
        return str(payload["Error"])
    return None


class TuyaController:
    def __init__(self, devices: list[dict]):
        # devices: list of {name, device_id, local_key, ip, version}
        # Keyed by lowercased name -> LIST of entries: duplicate names are
        # legitimate (same label reused in the Tuya app) and must not clobber.
        self._devices: dict[str, list[dict]] = {}
        for d in devices:
            self._devices.setdefault(d["name"].lower(), []).append(d)

    def _all_devices(self) -> list[dict]:
        return [dev for entries in self._devices.values() for dev in entries]

    def _find_devices_by_category(self, category: str) -> list[dict]:
        """Return all devices that match a category string such as 'lights' or 'bedroom lights'."""
        if category.strip().lower() == "all":
            return self._all_devices()
        terms = category.lower().split()
        return [
            dev for name, entries in self._devices.items()
            if all(
                any(exp in name for exp in _CATEGORY_EXPANSION.get(term, [term]))
                for term in terms
            )
            for dev in entries
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
        # Tuya bulbs put their power switch on DPS 20 (switch_led); outlets
        # use DPS 1. The wrong index gets ACKed but changes nothing.
        switch_dps = int(dev.get("switch_dps", 1))
        if action == "on":
            resp = device.turn_on(switch=switch_dps)
        elif action == "off":
            resp = device.turn_off(switch=switch_dps)
        elif action == "toggle":
            status = device.status()
            err = _payload_error(status)
            if err:
                return f"{dev['name']} failed ({err})."
            is_on = status.get("dps", {}).get(str(switch_dps), False)
            resp = device.turn_off(switch=switch_dps) if is_on else device.turn_on(switch=switch_dps)
        else:
            return f"{dev['name']}: unknown action '{action}'."

        err = _payload_error(resp)
        if err:
            return f"{dev['name']} failed ({err})."
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

    def _control_many(self, devices: list[dict], action: str) -> list[str]:
        with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(devices))) as pool:
            return list(pool.map(lambda d: self._safe_control(d, action), devices))

    def control(self, device_name: str, action: str) -> str:
        # 1. Exact name match — controls every entry sharing that name
        key = device_name.lower()
        if key in self._devices:
            results = self._control_many(self._devices[key], action)
            return "; ".join(results)

        # 2. Category match ("lights", "bedroom lights", "fans", "all", …)
        devices = self._find_devices_by_category(device_name)
        if devices:
            results = self._control_many(devices, action)
            return f"Controlled {len(devices)} device(s): " + "; ".join(results)

        # 3. Fuzzy name match (substring fallback)
        for dev_key, entries in self._devices.items():
            if key in dev_key or dev_key in key:
                return "; ".join(self._control_many(entries, action))

        return f"Device '{device_name}' not found. Check your config.yaml device list."
