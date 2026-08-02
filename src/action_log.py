import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Optional

_logger: Optional[logging.Logger] = None


def configure(log_path: str = "logs/actions.txt") -> None:
    """(Re)configure the action logger to write JSON Lines to log_path."""
    global _logger
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("compressor.actions")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _logger = logger


def _write(event: str, unit: str, **fields) -> None:
    if _logger is None:
        return
    try:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "unit": unit,
            "event": event,
            **fields,
        }
        _logger.info(json.dumps(record))
    except Exception as e:
        print(f"[ActionLog Error] {e}")


def log_wake(unit: str) -> None:
    _write("wake", unit)


def log_query(unit: str, text: str) -> None:
    _write("query", unit, text=text)


def log_tool_call(unit: str, tool_name: str, tool_input: dict, result: str) -> None:
    _write("tool_call", unit, tool_name=tool_name, tool_input=tool_input, result=result)


def log_response(unit: str, text: str) -> None:
    _write("response", unit, text=text)


def log_error(unit: str, context: str, error: str) -> None:
    _write("error", unit, context=context, error=error)
