import json

import yaml


def _write_tinytuya_json(root):
    (root / "tinytuya.json").write_text(
        json.dumps({
            "apiKey": "key",
            "apiSecret": "secret",
            "apiRegion": "us",
            "apiDeviceID": "dev-id",
        })
    )


def _write_config_yaml(root, devices):
    (root / "config.yaml").write_text(
        yaml.dump({"role": "host", "wake_word": "compressor", "tuya": {"devices": devices}})
    )


def test_sync_copies_local_key_field_from_cloud_response(mocker, tmp_path):
    """Regression test: Tuya's cloud API returns the field as 'local_key', not 'key'."""
    mocker.patch("src.tasks.tuya_sync._PROJECT_ROOT", tmp_path)
    _write_tinytuya_json(tmp_path)
    _write_config_yaml(tmp_path, [
        {"name": "Living Room Light", "device_id": "abc123", "local_key": "", "ip": "", "version": 3.3},
    ])

    mock_cloud_cls = mocker.patch("src.tasks.tuya_sync.tinytuya.Cloud")
    mock_cloud_cls.return_value.getdevices.return_value = [
        {"id": "abc123", "local_key": "real-local-key", "ip": "192.168.1.50", "version": "3.3"},
    ]

    from src.tasks import tuya_sync
    tuya_sync.run()

    updated_config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    device = updated_config["tuya"]["devices"][0]
    assert device["local_key"] == "real-local-key"
    assert device["ip"] == "192.168.1.50"


def test_sync_adds_new_device_with_local_key(mocker, tmp_path):
    mocker.patch("src.tasks.tuya_sync._PROJECT_ROOT", tmp_path)
    _write_tinytuya_json(tmp_path)
    _write_config_yaml(tmp_path, [])

    mock_cloud_cls = mocker.patch("src.tasks.tuya_sync.tinytuya.Cloud")
    mock_cloud_cls.return_value.getdevices.return_value = [
        {"id": "xyz789", "name": "Kitchen Bulb", "local_key": "another-real-key", "ip": "192.168.1.60", "version": "3.3"},
    ]

    from src.tasks import tuya_sync
    tuya_sync.run()

    updated_config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    device = updated_config["tuya"]["devices"][0]
    assert device["name"] == "Kitchen Bulb"
    assert device["local_key"] == "another-real-key"


def test_sync_calls_on_complete_with_updated_devices(mocker, tmp_path):
    mocker.patch("src.tasks.tuya_sync._PROJECT_ROOT", tmp_path)
    _write_tinytuya_json(tmp_path)
    _write_config_yaml(tmp_path, [])

    mock_cloud_cls = mocker.patch("src.tasks.tuya_sync.tinytuya.Cloud")
    mock_cloud_cls.return_value.getdevices.return_value = [
        {"id": "xyz789", "name": "Kitchen Bulb", "local_key": "another-real-key", "ip": "192.168.1.60", "version": "3.3"},
    ]

    on_complete = mocker.Mock()
    from src.tasks import tuya_sync
    tuya_sync.run(on_complete=on_complete)

    on_complete.assert_called_once()
    devices = on_complete.call_args[0][0]
    assert devices[0]["local_key"] == "another-real-key"


def test_sync_skips_when_cloud_returns_no_devices(mocker, tmp_path, caplog):
    mocker.patch("src.tasks.tuya_sync._PROJECT_ROOT", tmp_path)
    _write_tinytuya_json(tmp_path)
    _write_config_yaml(tmp_path, [
        {"name": "Living Room Light", "device_id": "abc123", "local_key": "", "ip": "", "version": 3.3},
    ])

    mock_cloud_cls = mocker.patch("src.tasks.tuya_sync.tinytuya.Cloud")
    mock_cloud_cls.return_value.getdevices.return_value = []

    from src.tasks import tuya_sync
    tuya_sync.run()

    updated_config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert updated_config["tuya"]["devices"][0]["local_key"] == ""
