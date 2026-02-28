import pytest

DEVICES = [
    {"name": "Living Room Light", "device_id": "abc", "local_key": "xxx", "ip": "192.168.1.50", "version": 3.3},
    {"name": "Bedroom Fan", "device_id": "def", "local_key": "yyy", "ip": "192.168.1.51", "version": 3.3},
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
