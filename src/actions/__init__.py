from src.actions import (
    control_spotify,
    control_tuya_device,
    message_wezterm_tab,
    open_program,
    scan_network,
)

ACTIONS = {
    "control_tuya_device": control_tuya_device.run,
    "control_spotify": control_spotify.run,
    "open_program": open_program.run,
    "scan_network": scan_network.run,
    "message_wezterm_tab": message_wezterm_tab.run,
}
