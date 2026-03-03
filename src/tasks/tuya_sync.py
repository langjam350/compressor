"""
Daily Tuya cloud sync task.

Downloads the latest device list from Tuya cloud, refreshes tuya-raw.json,
and updates config.yaml with current IPs and local keys.  After the config
is written, the optional `on_complete` callback receives the updated device
list so the running TuyaController can reload without a restart.
"""

import json
import logging
from pathlib import Path
from typing import Callable

import tinytuya
import yaml

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def run(on_complete: Callable[[list[dict]], None] | None = None) -> None:
    """Download devices from Tuya cloud and refresh config.yaml.

    Args:
        on_complete: Optional callback invoked with the updated device list
                     (as stored in config.yaml) after a successful sync.
    """
    tinytuya_json = _PROJECT_ROOT / "tinytuya.json"
    if not tinytuya_json.exists():
        log.warning("[TuyaSync] tinytuya.json not found – skipping.")
        return

    with open(tinytuya_json, encoding="utf-8") as f:
        creds = json.load(f)

    # ------------------------------------------------------------------ #
    # 1. Download from cloud                                               #
    # ------------------------------------------------------------------ #
    log.info("[TuyaSync] Connecting (region=%s)…", creds.get("apiRegion", "?"))
    cloud = tinytuya.Cloud(
        apiRegion=creds["apiRegion"],
        apiKey=creds["apiKey"],
        apiSecret=creds["apiSecret"],
    )

    # verbose=True makes tinytuya write its own copies of the files; we also
    # write them ourselves below so the format stays consistent.
    # getdevices() can return a dict {"result": [...], ...} or a plain list.
    raw = cloud.getdevices(verbose=True) or {}
    devices: list[dict] = raw.get("result", []) if isinstance(raw, dict) else (raw or [])

    if not devices:
        log.warning("[TuyaSync] Cloud returned no devices.")
        return

    log.info("[TuyaSync] Received %d device(s) from cloud.", len(devices))

    with open(_PROJECT_ROOT / "tuya-raw.json", "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 2. Update config.yaml                                                #
    # ------------------------------------------------------------------ #
    config_yaml = _PROJECT_ROOT / "config.yaml"
    if not config_yaml.exists():
        log.warning("[TuyaSync] config.yaml not found – skipping config update.")
        return

    with open(config_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    cloud_by_id: dict[str, dict] = {d["id"]: d for d in devices if d.get("id")}
    existing: list[dict] = config.setdefault("tuya", {}).setdefault("devices", [])
    existing_ids: set[str] = {e["device_id"] for e in existing if e.get("device_id")}

    refreshed = 0
    for entry in existing:
        cloud_dev = cloud_by_id.get(entry.get("device_id", ""))
        if not cloud_dev:
            continue
        if cloud_dev.get("key"):
            entry["local_key"] = cloud_dev["key"]
        if cloud_dev.get("ip"):
            entry["ip"] = cloud_dev["ip"]
        if cloud_dev.get("version"):
            try:
                entry["version"] = float(cloud_dev["version"])
            except (ValueError, TypeError):
                pass
        refreshed += 1

    added = 0
    for dev_id, cloud_dev in cloud_by_id.items():
        if dev_id in existing_ids:
            continue
        name = cloud_dev.get("name") or f"Device_{dev_id[-6:]}"
        try:
            version = float(cloud_dev.get("version", 3.3))
        except (ValueError, TypeError):
            version = 3.3
        existing.append(
            {
                "name": name,
                "device_id": dev_id,
                "local_key": cloud_dev.get("key", ""),
                "ip": cloud_dev.get("ip", ""),
                "version": version,
            }
        )
        log.info("[TuyaSync] New device added to config: %s", name)
        added += 1

    with open(config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    log.info("[TuyaSync] Config refreshed: %d updated, %d added.", refreshed, added)

    if on_complete:
        on_complete(existing)
