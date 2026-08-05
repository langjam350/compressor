from src.actions import control_spotify, control_tuya_device

ACTIONS = {
    "control_tuya_device": control_tuya_device.run,
    "control_spotify": control_spotify.run,
}
