"""
Local network scan for Tuya devices.
Does NOT require cloud API access - uses UDP broadcast to discover devices.
Note: local_key values still require cloud access (see README for instructions).
"""
import json
import sys
import tinytuya


def scan_devices(timeout_retries: int = 18) -> None:
    print("Scanning local network for Tuya devices (UDP broadcast)...")
    print("This may take up to 30 seconds.\n")

    devices = tinytuya.deviceScan(verbose=False, maxretry=timeout_retries, poll=False)

    if not devices:
        print("No Tuya devices found on the network.")
        print("Make sure your devices are powered on and on the same network.")
        return

    print(f"Found {len(devices)} device(s):\n")
    print(f"{'IP':<18} {'Device ID':<26} {'Version':<10} {'Product Key'}")
    print("-" * 80)

    config_entries = []
    for ip, info in devices.items():
        dev_id = info.get("gwId", "unknown")
        version = info.get("version", "3.3")
        product_key = info.get("productKey", "unknown")
        print(f"{ip:<18} {dev_id:<26} {str(version):<10} {product_key}")
        config_entries.append({
            "name": f"Device_{dev_id[-6:]}",
            "device_id": dev_id,
            "local_key": "REPLACE_WITH_LOCAL_KEY",
            "ip": ip,
            "version": float(version) if version else 3.3,
        })

    print("\n--- config.yaml snippet (fill in local_key from Tuya IoT portal) ---")
    print("tuya:")
    print("  devices:")
    for entry in config_entries:
        print(f"    - name: {entry['name']}")
        print(f"      device_id: {entry['device_id']}")
        print(f"      local_key: {entry['local_key']}")
        print(f"      ip: {entry['ip']}")
        print(f"      version: {entry['version']}")

    print("\nTo get local_key values:")
    print("  1. Log in to https://iot.tuya.com")
    print("  2. Go to Cloud > Development > your project > Devices")
    print("  3. Find each device and copy its 'Local Key'")


if __name__ == "__main__":
    retries = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    scan_devices(retries)
