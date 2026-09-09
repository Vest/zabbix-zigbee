#!/usr/bin/env python3
"""Bulk-import the Zigbee (zigbee2mqtt) Zabbix templates via the Zabbix API (7.4).

Imports every template YAML in dependency order (the common base before the
device templates that link it), so linked-template references resolve. Safe to
re-run: createMissing + updateExisting; items/triggers/dashboards use
deleteMissing so the YAML is authoritative. Config from scripts/.env (or real
env vars; env wins): ZABBIX_URL, ZABBIX_TOKEN.

Usage:
    python3 import_templates.py               # all templates, in order
    python3 import_templates.py FILE [FILE..] # only the given files, in order
    python3 import_templates.py --insecure    # skip TLS verification
    python3 import_templates.py --dry-run      # list what would import, no network
Stdlib only — no pip install required.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEMPLATES = os.path.join(REPO, "templates")

# Dependency-correct order: common base BEFORE the device templates that link it.
DEFAULT_FILES = [
    "mqtt/zigbee2mqtt_common_by_mqtt.yaml",              # base
    "mqtt/sonoff_swv_zf2_water_valve_by_mqtt.yaml",
    "mqtt/tuya_ts011f_smart_plug_by_mqtt.yaml",
    "mqtt/tuya_ts0201_temp_humidity_sensor_by_mqtt.yaml",
    "mqtt/zigbee2mqtt_bridge_by_mqtt.yaml",              # standalone
]

RULES = {
    "template_groups": {"createMissing": True, "updateExisting": True},
    "templates": {"createMissing": True, "updateExisting": True},
    "templateLinkage": {"createMissing": True, "deleteMissing": False},
    "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "valueMaps": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
    "templateDashboards": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
}


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def api_endpoint(url):
    url = url.rstrip("/")
    if not url.endswith("/api_jsonrpc.php"):
        url += "/api_jsonrpc.php"
    return url


def import_file(endpoint, token, ctx, path, req_id):
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    payload = {
        "jsonrpc": "2.0",
        "method": "configuration.import",
        "params": {"format": "yaml", "source": source, "rules": RULES},
        "id": req_id,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if "error" in body:
        err = body["error"]
        detail = err.get("data") or err.get("message") or str(err)
        raise RuntimeError(detail)
    return body.get("result")


def main():
    ap = argparse.ArgumentParser(description="Bulk-import Zigbee Zabbix templates.")
    ap.add_argument("files", nargs="*", help="Template YAML files (default: all, in order).")
    ap.add_argument("--insecure", action="store_true", help="Skip TLS verification.")
    ap.add_argument("--dry-run", action="store_true", help="List files; no network.")
    args = ap.parse_args()

    load_dotenv(os.path.join(HERE, ".env"))

    if args.files:
        resolved = [f if os.path.isabs(f) else os.path.abspath(f) for f in args.files]
    else:
        resolved = [os.path.join(TEMPLATES, f) for f in DEFAULT_FILES]

    missing = [f for f in resolved if not os.path.exists(f)]
    if missing:
        print("ERROR: file(s) not found:", file=sys.stderr)
        for m in missing:
            print("  " + m, file=sys.stderr)
        return 2

    if args.dry_run:
        print("Would import %d file(s) in this order:" % len(resolved))
        for f in resolved:
            print("  " + os.path.basename(f))
        return 0

    url = os.environ.get("ZABBIX_URL")
    token = os.environ.get("ZABBIX_TOKEN")
    if not url or not token:
        print("ERROR: ZABBIX_URL and ZABBIX_TOKEN must be set (in .env or environment).", file=sys.stderr)
        return 2

    endpoint = api_endpoint(url)
    ctx = ssl._create_unverified_context() if args.insecure else None

    print("Importing %d template(s) -> %s" % (len(resolved), endpoint))
    failures = 0
    for i, path in enumerate(resolved, start=1):
        name = os.path.basename(path)
        try:
            import_file(endpoint, token, ctx, path, i)
            print("OK    " + name)
        except urllib.error.HTTPError as e:
            failures += 1
            print("FAIL  %s: HTTP %s %s" % (name, e.code, e.reason), file=sys.stderr)
        except urllib.error.URLError as e:
            failures += 1
            print("FAIL  %s: cannot reach %s (%s)" % (name, endpoint, e.reason), file=sys.stderr)
        except Exception as e:
            failures += 1
            print("FAIL  %s: %s" % (name, e), file=sys.stderr)

    if failures:
        print("\n%d of %d import(s) failed." % (failures, len(resolved)), file=sys.stderr)
        return 1
    print("\nAll %d template(s) imported successfully." % len(resolved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
