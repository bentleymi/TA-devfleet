#!/usr/bin/env python3
"""Emit one JSON event per cycle with PCI/USB inventory counts and device delta."""
import sys

from devfleet_common import discover, emit, events_payload, fail

DEGRADED = {
    "status": "absent",
    "pci_count": 0,
    "usb_count": 0,
    "new_devices": [],
    "removed_devices": [],
}


def main():
    try:
        data = discover()
        emit(events_payload(data))
    except Exception as exc:
        fail(str(exc))
        emit(dict(DEGRADED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
