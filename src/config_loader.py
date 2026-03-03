import yaml

REQUIRED_KEYS = ["role", "wake_word", "anthropic_api_key"]


class ConfigError(Exception):
    pass


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)

    for key in REQUIRED_KEYS:
        if key not in config:
            raise ConfigError(f"Missing required config key: '{key}'")

    if config["role"] == "client" and "host_ip" not in config:
        raise ConfigError("Clients must specify 'host_ip' in config")

    return config
