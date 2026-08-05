from src.actions import control_spotify, control_tuya_device, open_program

ACTIONS = {
    "control_tuya_device": control_tuya_device.run,
    "control_spotify": control_spotify.run,
    "open_program": open_program.run,
}
