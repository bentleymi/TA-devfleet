#!/usr/bin/env python3
"""Emit flat numeric metrics (one JSON event per cycle) for analytics."""
import sys

from devfleet_common import discover, emit, fail, metrics_payload

DEGRADED = {"pci_count": 0, "usb_count": 0, "device_delta": 0}


def main():
    try:
        data = discover()
        emit(metrics_payload(data))
    except Exception as exc:
        fail(str(exc))
        emit(dict(DEGRADED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
