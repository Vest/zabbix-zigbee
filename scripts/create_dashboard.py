#!/usr/bin/env python3
"""Create/update the "Zigbee fleet" Zabbix dashboard via the API (7.4).

Standalone (non-template) dashboard, so it is created through dashboard.create
(NOT configuration.import — that path does not accept standalone dashboards).
It references the Zigbee hosts/items by name; those hosts must exist first
(linked to the templates, with {$Z2M.TOPIC} set). Idempotent: if a dashboard
with the same name exists it is updated in place.

Config from scripts/.env (or env): ZABBIX_URL, ZABBIX_TOKEN.
Usage: python3 scripts/create_dashboard.py [--insecure]

Layout is on Zabbix's 72-column grid (x 0-71, y 0-63). Field type codes:
0=integer, 1=string, 4=item (see dashboard API reference).
Stdlib only.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DASH_NAME = "Zigbee fleet"

# Battery / temp-humidity devices etc. referenced by host technical name.
GARDEN = "garden-pump"
SENSOR = "base-out"
PLUGS = ["living-plug", "base-plug-1", "base-plug-2"]
BATTERY_HOSTS = ["garden-pump", "base-out"]
ALL_DEVICES = ["garden-pump", "living-plug", "base-plug-1", "base-plug-2", "base-out"]
BRIDGE = "z2m-bridge"

# Okabe-Ito-ish distinct hues (hex, no #): identity by entity, assigned in order.
COLORS = ["1F77B4", "FF7F0E", "2CA02C", "D62728", "9467BD", "8C564B"]


def load_dotenv(path):
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def api(endpoint, token, ctx, method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        body = json.loads(r.read().decode())
    if "error" in body:
        raise RuntimeError(body["error"].get("data") or body["error"])
    return body["result"]


def S(name, value):   # string field
    return {"type": 1, "name": name, "value": value}


def I(name, value):   # integer field
    return {"type": 0, "name": str(name), "value": int(value)}


def ITEM(name, itemid):  # item-reference field
    return {"type": 4, "name": name, "value": str(itemid)}


def graph(title, x, y, w, h, series, time_from="now-7d", stacked=False):
    """svggraph: one data set per (host,item-name), each its own color."""
    fields = [S("time_period.from", time_from), S("time_period.to", "now")]
    for idx, (host, itemname) in enumerate(series):
        fields.append(S("ds.%d.hosts.0" % idx, host))
        fields.append(S("ds.%d.items.0" % idx, itemname))
        fields.append(S("ds.%d.color" % idx, COLORS[idx % len(COLORS)]))
        fields.append(I("ds.%d.width" % idx, 2))
        if stacked:
            fields.append(I("ds.%d.fill" % idx, 5))
    return {"type": "svggraph", "name": title, "x": x, "y": y, "width": w, "height": h, "fields": fields}


def value(title, x, y, w, h, itemid, agg=None, period=None, units=None):
    """item value widget. agg: 5=sum (see item widget). Shows big number."""
    fields = [ITEM("itemid", itemid)]
    if agg is not None:
        fields.append(I("aggregate_function", agg))
        if period:
            fields.append(S("time_period.from", period))
            fields.append(S("time_period.to", "now"))
    if units:
        fields.append(S("units", units))
        fields.append(I("units_show", 1))
    return {"type": "item", "name": title, "x": x, "y": y, "width": w, "height": h, "fields": fields}


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

    # Resolve item IDs we need to reference by id (value widgets).
    def itemid(host, key):
        r = api(url, token, ctx, "item.get", {
            "output": ["itemid"], "host": host, "filter": {"key_": key}})
        if not r:
            raise SystemExit("item not found: %s %s (does the host exist + is it linked?)" % (host, key))
        return r[0]["itemid"]

    water_total = itemid(GARDEN, "z2m.valve.event_litres_total")
    rt_volume = itemid(GARDEN, "z2m.valve.rt_volume")
    abnormal = itemid(GARDEN, "z2m.valve.abnormal")
    bridge_online = itemid(BRIDGE, "z2m.bridge.online")
    device_count = itemid(BRIDGE, "z2m.bridge.device_count")
    host_mem = itemid(BRIDGE, "z2m.bridge.host_mem_pct")

    # --- build the single overview page on the 72-col grid ---
    widgets = []
    # Row 1: gateway + water headline tiles (each 18 wide, 3 tall)
    widgets.append(value("Bridge online", 0, 0, 12, 3, bridge_online))
    widgets.append(value("Devices online", 12, 0, 12, 3, device_count))
    widgets.append(value("Host memory", 24, 0, 12, 3, host_mem, units="%"))
    widgets.append(value("Water today (L)", 36, 0, 18, 3, water_total, agg=5, period="now-1d"))
    widgets.append(value("Valve abnormal", 54, 0, 18, 3, abnormal))

    # Row 2: water per event (30d) + live volume
    widgets.append(graph("Water used per event (30d)", 0, 3, 48, 6,
                         [(GARDEN, "Water used per completed event (both channels)")],
                         time_from="now-30d", stacked=True))
    widgets.append(value("Live irrigation volume (L)", 48, 3, 24, 6, rt_volume))

    # Row 3: battery levels (both battery devices) + temp/humidity
    widgets.append(graph("Battery levels (7d)", 0, 9, 24, 7,
                         [(h, "Battery") for h in BATTERY_HOSTS]))
    widgets.append(graph("Temperature (7d)", 24, 9, 24, 7,
                         [(SENSOR, "Temperature")]))
    widgets.append(graph("Humidity (7d)", 48, 9, 24, 7,
                         [(SENSOR, "Humidity")]))

    # Row 4: link quality statistic (all devices) + plug power
    widgets.append(graph("Link quality / LQI (7d)", 0, 16, 36, 7,
                         [(h, "Link quality (LQI)") for h in ALL_DEVICES]))
    widgets.append(graph("Plug power (7d)", 36, 16, 36, 7,
                         [(h, "Power") for h in PLUGS]))

    dash = {
        "name": DASH_NAME,
        "display_period": 60,
        "auto_start": 1,
        "pages": [{"name": "Overview", "widgets": widgets}],
    }

    existing = api(url, token, ctx, "dashboard.get",
                   {"output": ["dashboardid"], "filter": {"name": DASH_NAME}})
    if existing:
        dash["dashboardid"] = existing[0]["dashboardid"]
        r = api(url, token, ctx, "dashboard.update", dash)
        print("Updated dashboard '%s' (id %s)" % (DASH_NAME, r["dashboardids"][0]))
    else:
        r = api(url, token, ctx, "dashboard.create", dash)
        print("Created dashboard '%s' (id %s)" % (DASH_NAME, r["dashboardids"][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
