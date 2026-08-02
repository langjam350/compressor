import pytest
from pathlib import Path


def write_config(tmp_path, content: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return str(p)


def test_load_config_returns_dict(tmp_path):
    path = write_config(tmp_path, "role: host\nwake_word: compressor\nanthropic_api_key: key123\n")
    from src.config_loader import load_config
    result = load_config(path)
    assert result["role"] == "host"
    assert result["wake_word"] == "compressor"


def test_load_config_missing_required_key_raises(tmp_path):
    path = write_config(tmp_path, "role: host\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="wake_word"):
        load_config(path)


def test_load_config_file_not_found():
    from src.config_loader import load_config
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")


def test_load_config_client_requires_host_ip(tmp_path):
    path = write_config(tmp_path, "role: client\nwake_word: compressor\nanthropic_api_key: key\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="host_ip"):
        load_config(path)
