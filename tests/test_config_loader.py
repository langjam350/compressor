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


def test_load_config_follower_requires_host_ip(tmp_path):
    path = write_config(tmp_path, "role: follower\nwake_word: compressor\nanthropic_api_key: key\nunit_name: Kitchen\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="host_ip"):
        load_config(path)


def test_load_config_follower_requires_unit_name(tmp_path):
    path = write_config(tmp_path, "role: follower\nwake_word: compressor\nanthropic_api_key: key\nhost_ip: 192.168.1.100\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="unit_name"):
        load_config(path)


def test_load_config_follower_with_host_ip_and_unit_name_succeeds(tmp_path):
    path = write_config(tmp_path, "role: follower\nwake_word: compressor\nanthropic_api_key: key\nhost_ip: 192.168.1.100\nunit_name: Kitchen\n")
    from src.config_loader import load_config
    result = load_config(path)
    assert result["role"] == "follower"
    assert result["unit_name"] == "Kitchen"


def test_load_config_host_requires_anthropic_api_key(tmp_path):
    path = write_config(tmp_path, "role: host\nwake_word: compressor\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="anthropic_api_key"):
        load_config(path)


def test_load_config_follower_without_anthropic_api_key_succeeds(tmp_path):
    path = write_config(tmp_path, "role: follower\nwake_word: compressor\nhost_ip: 192.168.1.100\nunit_name: Kitchen\n")
    from src.config_loader import load_config
    result = load_config(path)
    assert result["role"] == "follower"
    assert "anthropic_api_key" not in result


def test_load_config_invalid_role_raises(tmp_path):
    path = write_config(tmp_path, "role: bogus\nwake_word: compressor\n")
    from src.config_loader import load_config, ConfigError
    with pytest.raises(ConfigError, match="Invalid role"):
        load_config(path)
