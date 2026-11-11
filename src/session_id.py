import secrets

SESSION_ID_BYTES = 8


def generate_session_id() -> str:
    """A fresh opaque identifier for one process run.

    Not a secret and not an access credential — it's only for correlating
    this run's actions/logs/coordinator messages, so it's safe to log,
    broadcast, or hand to a peer. Per-computer authentication is a separate,
    still-open mechanism.
    """
    return secrets.token_hex(SESSION_ID_BYTES)
