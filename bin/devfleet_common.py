"""Shared collection logic for TA-devfleet scripted inputs (PCI/USB inventory delta)."""
import hashlib
import json
import os
import subprocess
import sys

STATE_DIR = "/var/tmp"
LSPCI_CANDIDATES = ("/usr/bin/lspci", "/usr/sbin/lspci")
LSUSB_CANDIDATES = ("/usr/bin/lsusb", "/usr/sbin/lsusb")
TOOL_TIMEOUT = 25
LINES_CAP = 500
DIFF_CAP = 20


def _find(candidates):
    for path in candidates:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None


def _run_tool(candidates, timeout=TOOL_TIMEOUT):
    """Run an inventory tool; return sorted lines, or None if the tool is absent/failed."""
    path = _find(candidates)
    if path is None:
        return None
    try:
        p = subprocess.run([path], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return sorted(line.rstrip() for line in p.stdout.splitlines() if line.rstrip())


def _signature(lines):
    return hashlib.md5(("\n".join(lines)).encode("utf-8")).hexdigest()


def _state_path():
    """Per-input state file: named after the entry script's filename stem so the
    events and metrics inputs never read each other's freshly written state."""
    main = sys.modules.get("__main__")
    script = getattr(main, "__file__", None) or sys.argv[0]
    stem = os.path.splitext(os.path.basename(script))[0]
    return os.path.join(STATE_DIR, "ta_devfleet_state.%s.json" % stem)


def _load_state(path):
    empty = {"pci": None, "usb": None}
    try:
        with open(path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return empty
    if not isinstance(state, dict):
        return empty
    out = {}
    for bus in ("pci", "usb"):
        lines = state.get(bus + "_lines")
        if isinstance(lines, list) and all(isinstance(line, str) for line in lines):
            out[bus] = lines
        else:
            out[bus] = None
    return out


def _save_state(data, path):
    payload = {
        "pci_md5": data.get("pci_signature"),
        "usb_md5": data.get("usb_signature"),
        "pci_lines": data["pci_lines"][:LINES_CAP] if data["pci_lines"] is not None else None,
        "usb_lines": data["usb_lines"][:LINES_CAP] if data["usb_lines"] is not None else None,
    }
    tmp_path = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp_path, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp_path, path)
    except OSError as exc:
        sys.stderr.write("TA-devfleet: could not save state file %s: %s\n" % (path, exc))
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _diff(current, previous):
    """Lines in current not in previous, and vice versa. No data on either side -> no delta."""
    if current is None or previous is None:
        return [], []
    cur_set = set(current)
    prev_set = set(previous)
    return [line for line in current if line not in prev_set], [line for line in previous if line not in cur_set]


def discover():
    state_path = _state_path()
    pci_lines = _run_tool(LSPCI_CANDIDATES)
    usb_lines = _run_tool(LSUSB_CANDIDATES)
    pci_sig = _signature(pci_lines) if pci_lines is not None else None
    usb_sig = _signature(usb_lines) if usb_lines is not None else None

    prev = _load_state(state_path)
    new_pci, rem_pci = _diff(pci_lines, prev["pci"])
    new_usb, rem_usb = _diff(usb_lines, prev["usb"])
    device_delta = len(new_pci) + len(rem_pci) + len(new_usb) + len(rem_usb)
    new_devices = (new_pci + new_usb)[:DIFF_CAP]
    removed_devices = (rem_pci + rem_usb)[:DIFF_CAP]

    if pci_lines is None and usb_lines is None:
        status = "absent"
    elif device_delta > 0:
        status = "alarm"
    else:
        status = "ok"

    data = {
        "status": status,
        "pci_lines": pci_lines,
        "usb_lines": usb_lines,
        "pci_count": len(pci_lines) if pci_lines is not None else 0,
        "usb_count": len(usb_lines) if usb_lines is not None else 0,
        "pci_signature": pci_sig,
        "usb_signature": usb_sig,
        "new_devices": new_devices,
        "removed_devices": removed_devices,
        "device_delta": device_delta,
    }
    _save_state(data, state_path)
    return data


def events_payload(data):
    payload = {
        "status": data.get("status", "absent"),
        "pci_count": data.get("pci_count", 0),
        "usb_count": data.get("usb_count", 0),
        "new_devices": data.get("new_devices", []),
        "removed_devices": data.get("removed_devices", []),
        "device_delta": data["device_delta"],
    }
    if data.get("pci_signature") is not None:
        payload["pci_signature"] = data["pci_signature"]
    if data.get("usb_signature") is not None:
        payload["usb_signature"] = data["usb_signature"]
    return payload


def metrics_payload(data):
    return {
        "pci_count": int(data.get("pci_count") or 0),
        "usb_count": int(data.get("usb_count") or 0),
        "device_delta": int(data.get("device_delta") or 0),
    }


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message):
    sys.stderr.write("TA-devfleet collection error: %s\n" % message)
    return 1
