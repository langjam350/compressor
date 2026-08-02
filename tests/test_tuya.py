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


# --- resilience: skips, per-device isolation, timeouts ---

MIXED_DEVICES = [
    {"name": "Good Light", "device_id": "g1", "local_key": "k1", "ip": "192.168.0.10", "version": 3.3},
    {"name": "No IP Light", "device_id": "n1", "local_key": "k2", "ip": "", "version": 3.3},
    {"name": "No Key Light", "device_id": "n2", "local_key": "", "ip": "192.168.0.11", "version": 3.3},
    {"name": "Broken Light", "device_id": "b1", "local_key": "k3", "ip": "192.168.0.12", "version": 3.3},
]


def test_device_without_ip_is_skipped_not_scanned(mocker):
    """Empty ip must NOT construct OutletDevice (tinytuya would run an 18s UDP scan then raise)."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    result = ctrl.control("No IP Light", "on")

    mock_device_cls.assert_not_called()
    assert "no ip" in result.lower() or "skipped" in result.lower()


def test_device_without_local_key_is_skipped(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    result = ctrl.control("No Key Light", "on")

    mock_device_cls.assert_not_called()
    assert "no local key" in result.lower() or "skipped" in result.lower()


def test_one_failing_device_does_not_abort_category(mocker):
    """A raise from one device must not prevent the others from being controlled."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    good = mocker.MagicMock()
    broken = mocker.MagicMock()
    broken.turn_on.side_effect = OSError("connection refused")

    def factory(dev_id, address, local_key, version, **kwargs):
        return broken if dev_id == "b1" else good

    mock_device_cls.side_effect = factory

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    result = ctrl.control("lights", "on")

    good.turn_on.assert_called_once()          # Good Light still controlled
    assert "Good Light" in result
    assert "failed" in result.lower() or "error" in result.lower()  # Broken Light reported


def test_outlet_device_constructed_with_tight_timeouts(mocker):
    """Defaults (5s timeout x 5 retries) block far too long; must be tightened."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    ctrl.control("Good Light", "on")

    kwargs = mock_device_cls.call_args.kwargs
    assert kwargs.get("connection_timeout", 99) <= 3
    assert kwargs.get("connection_retry_limit", 99) <= 1


# --- false-success detection and duplicate-name handling ---

def test_error_payload_from_tinytuya_reported_as_failure(mocker):
    """tinytuya returns error payloads instead of raising on some failures —
    a response containing 'Error' must not be reported as success."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value
    mock_inst.turn_on.return_value = {"Error": "Network Error: Unable to Connect", "Err": "901"}

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    result = ctrl.control("Good Light", "on")

    assert "turned on" not in result.lower()
    assert "failed" in result.lower() or "error" in result.lower()


def test_success_payload_still_reports_success(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value
    mock_inst.turn_on.return_value = {"dps": {"1": True}}

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(MIXED_DEVICES)
    result = ctrl.control("Good Light", "on")

    assert "turned on" in result.lower()


DUPLICATE_NAME_DEVICES = [
    {"name": "Office Light 1", "device_id": "dup-a", "local_key": "", "ip": "", "version": 3.3},
    {"name": "Office Light 1", "device_id": "dup-b", "local_key": "k", "ip": "192.168.0.79", "version": 3.3},
]


def test_duplicate_names_are_not_clobbered(mocker):
    """Two config entries with the same name must BOTH be kept — controlling
    that name attempts every entry instead of silently dropping one."""
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value
    mock_inst.turn_on.return_value = {"dps": {"1": True}}

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DUPLICATE_NAME_DEVICES)
    result = ctrl.control("Office Light 1", "on")

    # The usable duplicate (dup-b) was controlled...
    assert mock_device_cls.call_args.kwargs["dev_id"] == "dup-b"
    assert "turned on" in result.lower()
    # ...and the unusable one is reported as skipped, not vanished.
    assert "skipped" in result.lower()


def test_duplicate_names_both_counted_in_category(mocker):
    mock_device_cls = mocker.patch("src.integrations.tuya.tinytuya.OutletDevice")
    mock_inst = mock_device_cls.return_value
    mock_inst.turn_on.return_value = {"dps": {"1": True}}

    from src.integrations.tuya import TuyaController
    ctrl = TuyaController(DUPLICATE_NAME_DEVICES)
    result = ctrl.control("lights", "on")

    assert "2 device(s)" in result
