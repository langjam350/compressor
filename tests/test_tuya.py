import pytest

DEVICES = [
    {"name": "Living Room Light", "device_id": "abc", "local_key": "xxx", "ip": "192.168.1.50", "version": 3.3},
    {"name": "Bedroom Fan", "device_id": "def", "local_key": "yyy", "ip": "192.168.1.51", "version": 3.3},
]

MULTI_DEVICES = [
    {"name": "Living Room Light", "device_id": "a", "local_key": "x", "ip": "1.1.1.1", "version": 3.3},
    {"name": "Bedroom Light", "device_id": "b", "local_key": "y", "ip": "1.1.1.2", "version": 3.3},
    {"name": "Kitchen Bulb 1", "device_id": "c", "local_key": "z", "ip": "1.1.1.3", "version": 3.3},
    {"name": "Bedroom Fan", "device_id": "d", "local_key": "w", "ip": "1.1.1.4", "version": 3.3},
]


def test_turn_on_device(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Living Room Light", "on")

    mock_inst.turn_on.assert_called_once()
    assert "on" in result.lower()


def test_turn_off_device(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Bedroom Fan", "off")

    mock_inst.turn_off.assert_called_once()
    assert "off" in result.lower()


def test_unknown_device_returns_error(mocker):
    mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    result = ctrl.control("Nonexistent Device", "on")

    assert "not found" in result.lower()


def test_fuzzy_device_match(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DEVICES)
    # "living room" is a substring of "Living Room Light"
    result = ctrl.control("living room", "on")

    mock_inst.turn_on.assert_called_once()


# --- category / decision matrix ---

def test_control_lights_turns_on_all_light_and_bulb_devices(mocker):
    """'lights' matches any device with light, lamp, or bulb in its name."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MULTI_DEVICES)
    ctrl.control("lights", "on")

    # Living Room Light, Bedroom Light, Kitchen Bulb 1 — 3 devices
    assert mock_inst.turn_on.call_count == 3


def test_control_bedroom_lights_filters_by_room(mocker):
    """'bedroom lights' matches only light-type devices that also contain 'bedroom'."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MULTI_DEVICES)
    ctrl.control("bedroom lights", "off")

    # Only Bedroom Light — not Living Room Light or Kitchen Bulb 1
    assert mock_inst.turn_off.call_count == 1


def test_control_fans_turns_on_fan_devices(mocker):
    """'fans' matches any device with fan in its name."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MULTI_DEVICES)
    ctrl.control("fans", "on")

    assert mock_inst.turn_on.call_count == 1


def test_control_all_controls_every_device(mocker):
    """'all' matches every registered device."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MULTI_DEVICES)
    ctrl.control("all", "off")

    assert mock_inst.turn_off.call_count == 4


def test_control_category_with_no_matches_returns_not_found(mocker):
    """An unrecognized category with no keyword matches returns a not-found message."""
    mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MULTI_DEVICES)
    result = ctrl.control("televisions", "on")

    assert "not found" in result.lower()
