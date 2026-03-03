import tinytuya

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

    def control(self, device_name: str, action: str) -> str:
        # 1. Exact name match
        key = device_name.lower()
        if key in self._devices:
            return self._control_single(self._devices[key], action)

        # 2. Category match ("lights", "bedroom lights", "fans", "all", …)
        devices = self._find_devices_by_category(device_name)
        if devices:
            results = [self._control_single(dev, action) for dev in devices]
            return f"Controlled {len(devices)} device(s): " + "; ".join(results)

        # 3. Fuzzy name match (substring fallback)
        for dev_key, dev in self._devices.items():
            if key in dev_key or dev_key in key:
                return self._control_single(dev, action)

        return f"Device '{device_name}' not found. Check your config.yaml device list."
