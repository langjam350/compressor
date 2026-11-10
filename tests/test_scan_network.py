import yaml


def _write_config_yaml(root, devices):
    (root / "config.yaml").write_text(
        yaml.dump({"role": "host", "wake_word": "compressor", "tuya": {"devices": devices}})
    )


def _ctx(mocker, **overrides):
    from src.actions.context import ActionContext
    defaults = dict(
        unit_name="host",
        tuya=mocker.MagicMock(),
        tuya_reload=mocker.Mock(),
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def test_scan_network_without_controller_reports_unconfigured(mocker):
    ctx = _ctx(mocker, tuya=None)
    from src.actions import scan_network
    assert scan_network.run(ctx, {}) == "Integration not configured."


def test_scan_network_reports_when_nothing_found(mocker, tmp_path):
    mocker.patch("src.actions.scan_network._PROJECT_ROOT", tmp_path)
    mocker.patch("src.actions.scan_network.scan_tuya.scan_devices", return_value={})

    from src.actions import scan_network
    ctx = _ctx(mocker)
    assert scan_network.run(ctx, {}) == "No devices found on the network."


def test_scan_network_fills_in_missing_ip_and_reloads_controller(mocker, tmp_path):
    mocker.patch("src.actions.scan_network._PROJECT_ROOT", tmp_path)
    _write_config_yaml(tmp_path, [
        {"name": "Bedroom Fan", "device_id": "abc123", "local_key": "key", "ip": "", "version": 3.3},
    ])
    mocker.patch(
        "src.actions.scan_network.scan_tuya.scan_devices",
        return_value={"192.168.1.50": {"gwId": "abc123", "version": "3.3"}},
    )

    from src.actions import scan_network
    ctx = _ctx(mocker)
    result = scan_network.run(ctx, {})

    updated_config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    device = updated_config["tuya"]["devices"][0]
    assert device["ip"] == "192.168.1.50"

    ctx.tuya_reload.assert_called_once_with(updated_config["tuya"]["devices"])
    assert "Bedroom Fan" in result
    assert "Ready to control now" in result


def test_scan_network_reports_no_match_for_unknown_devices(mocker, tmp_path):
    mocker.patch("src.actions.scan_network._PROJECT_ROOT", tmp_path)
    _write_config_yaml(tmp_path, [
        {"name": "Bedroom Fan", "device_id": "abc123", "local_key": "key", "ip": "", "version": 3.3},
    ])
    mocker.patch(
        "src.actions.scan_network.scan_tuya.scan_devices",
        return_value={"192.168.1.50": {"gwId": "someone-elses-device", "version": "3.3"}},
    )

    from src.actions import scan_network
    ctx = _ctx(mocker)
    result = scan_network.run(ctx, {})

    assert "none matched your configured devices" in result
    ctx.tuya_reload.assert_not_called()


def test_scan_network_already_up_to_date_skips_write_and_reload(mocker, tmp_path):
    mocker.patch("src.actions.scan_network._PROJECT_ROOT", tmp_path)
    _write_config_yaml(tmp_path, [
        {"name": "Bedroom Fan", "device_id": "abc123", "local_key": "key", "ip": "192.168.1.50", "version": 3.3},
    ])
    mocker.patch(
        "src.actions.scan_network.scan_tuya.scan_devices",
        return_value={"192.168.1.50": {"gwId": "abc123", "version": "3.3"}},
    )

    from src.actions import scan_network
    ctx = _ctx(mocker)
    result = scan_network.run(ctx, {})

    assert "Already up to date" in result
    ctx.tuya_reload.assert_not_called()
