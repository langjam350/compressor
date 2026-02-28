import tinytuya


class TuyaController:
    def __init__(self, devices: list[dict]):
        # devices: list of {name, device_id, local_key, ip, version}
        self._devices = {d["name"].lower(): d for d in devices}

    def _find_device(self, name: str) -> dict | None:
        key = name.lower()
        if key in self._devices:
            return self._devices[key]
        # Fuzzy: check if query is substring of any device name (or vice versa)
        for dev_key, dev in self._devices.items():
            if key in dev_key or dev_key in key:
                return dev
        return None

    def control(self, device_name: str, action: str) -> str:
        dev = self._find_device(device_name)
        if dev is None:
            return f"Device '{device_name}' not found. Check your config.yaml device list."

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
