import yaml

REQUIRED_KEYS = ["wake_word"]


class ConfigError(Exception):
    pass


def load_config(path: str = "config.yaml") -> dict:
    """Load and validate config.yaml.

    `role` is optional: leave it out and the unit elects its role from the
    tier list in units.json (see src/cluster.py). Setting it pins the unit to
    that role forever and skips the election — useful for a one-off debug run
    or a machine that must never take ownership. When it is set, the old
    per-role requirements below still apply.
    """
    with open(path) as f:
        config = yaml.safe_load(f)

    for key in REQUIRED_KEYS:
        if key not in config:
            raise ConfigError(f"Missing required config key: '{key}'")

    if "role" in config:
        if config["role"] not in ("host", "follower"):
            raise ConfigError(f"Invalid role '{config['role']}': must be 'host' or 'follower'")

        if config["role"] == "host":
            if "anthropic_api_key" not in config:
                raise ConfigError("Host must specify 'anthropic_api_key' in config")

        if config["role"] == "follower":
            if "host_ip" not in config:
                raise ConfigError("Followers must specify 'host_ip' in config")
            if "unit_name" not in config:
                raise ConfigError("Followers must specify 'unit_name' in config")

    return config
