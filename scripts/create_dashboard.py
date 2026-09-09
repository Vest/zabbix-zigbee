#!/usr/bin/env python3
"""Deploy the portable "Zigbee fleet overview" dashboard via the Zabbix API (7.4).

Standalone (non-template) dashboards are NOT part of configuration.export/import,
so the portable definition lives in dashboards/zigbee_fleet_overview.json and is
loaded here through dashboard.create/update (server-specific ids stripped). Most
widgets reference hosts/items by NAME + a host-group filter, so new Zigbee devices
appear automatically. A few single-value (item) widgets need a concrete itemid;
the JSON uses named placeholders that this script resolves against the live server:

    GARDEN_WATER_TOTAL   garden-pump   z2m.valve.event_litres_total
    GARDEN_RT_VOLUME     garden-pump   z2m.valve.rt_volume
    BRIDGE_ONLINE        z2m-bridge    z2m.bridge.online
    BRIDGE_DEVICE_COUNT  z2m-bridge    z2m.bridge.device_count
    BRIDGE_HOST_MEM      z2m-bridge    z2m.bridge.host_mem_pct

The Zigbee hosts (linked to the templates, {$Z2M.TOPIC} set) and the "Zigbee"
host group must exist first. Idempotent: updates in place if the dashboard exists.

Config from scripts/.env (or env): ZABBIX_URL, ZABBIX_TOKEN.
Usage: python3 scripts/create_dashboard.py [--insecure]
Stdlib only.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DASH_JSON = os.path.join(REPO, "dashboards", "zigbee_fleet_overview.json")

# placeholder -> (host, item key) resolved to a live itemid at deploy time.
PLACEHOLDERS = {
    "GARDEN_WATER_TOTAL": ("garden-pump", "z2m.valve.event_litres_total"),
    "GARDEN_RT_VOLUME":   ("garden-pump", "z2m.valve.rt_volume"),
    "BRIDGE_ONLINE":      ("z2m-bridge", "z2m.bridge.online"),
    "BRIDGE_DEVICE_COUNT":("z2m-bridge", "z2m.bridge.device_count"),
    "BRIDGE_HOST_MEM":    ("z2m-bridge", "z2m.bridge.host_mem_pct"),
}


def load_dotenv(path):
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(endpoint, token, ctx, method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        body = json.loads(r.read().decode())
    if "error" in body:
        raise RuntimeError(body["error"].get("data") or body["error"])
    return body["result"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()
    load_dotenv(os.path.join(HERE, ".env"))
    url = os.environ.get("ZABBIX_URL", "").rstrip("/")
    token = os.environ.get("ZABBIX_TOKEN")
    if not url or not token:
        print("ERROR: set ZABBIX_URL and ZABBIX_TOKEN (scripts/.env)", file=sys.stderr)
        return 2
    if not url.endswith("/api_jsonrpc.php"):
        url += "/api_jsonrpc.php"
    ctx = ssl._create_unverified_context() if args.insecure else None

    dash = json.load(open(DASH_JSON, encoding="utf-8"))

    # Resolve placeholders -> itemids
    resolved = {}
    for ph, (host, key) in PLACEHOLDERS.items():
        r = api(url, token, ctx, "item.get",
                {"output": ["itemid"], "host": host, "filter": {"key_": key}})
        if not r:
            print("ERROR: item not found for %s: host=%s key=%s "
                  "(host missing or not linked yet?)" % (ph, host, key), file=sys.stderr)
            return 1
        resolved[ph] = r[0]["itemid"]

    for page in dash["pages"]:
        for w in page["widgets"]:
            for f in w["fields"]:
                if f["value"] in resolved:
                    f["value"] = resolved[f["value"]]

    existing = api(url, token, ctx, "dashboard.get",
                   {"output": ["dashboardid"], "filter": {"name": dash["name"]}})
    if existing:
        dash["dashboardid"] = existing[0]["dashboardid"]
        r = api(url, token, ctx, "dashboard.update", dash)
        print("Updated dashboard '%s' (id %s)" % (dash["name"], r["dashboardids"][0]))
    else:
        r = api(url, token, ctx, "dashboard.create", dash)
        print("Created dashboard '%s' (id %s)" % (dash["name"], r["dashboardids"][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
