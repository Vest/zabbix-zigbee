# Zabbix Zigbee (zigbee2mqtt) Monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and live-import a Zabbix 7.4 template set that records home-automation statistics for zigbee2mqtt devices (garden-pump water usage, battery, link quality, temperature/humidity, plug power) plus z2m gateway health.

**Architecture:** Zabbix agent 2 MQTT plugin subscribes to `z2m/<device>` topics; one `mqtt.get` master item per device holds the full JSON blob; scalar metrics are dependent items parsing it via JSONPATH. A common base template is linked by device templates; the bridge template is standalone. Full design + metric tables: `docs/superpowers/specs/2026-09-09-zabbix-zigbee-monitoring-design.md` (authoritative — read before each task).

**Tech Stack:** Zabbix 7.4 (server 7.4.14 verified), agent 2 MQTT plugin, YAML template export format, stdlib Python 3 import script.

**Testing model (no code unit tests — declarative YAML):** the red/green loop per template is (1) **static validator** `scripts/validate.py` catches schema-rule violations, (2) **live import** `python3 scripts/import_templates.py <file>` against the real server is the authoritative check, (3) spot-check JSONPaths against the real payloads captured in the spec. Verify FAIL states where noted.

**UUIDs:** Every `uuid:` must be a fresh valid UUIDv4. Generate with `python3 -c "import uuid;print(uuid.uuid4().hex)"` as you write each file. NEVER reuse a UUID across files except the shared group UUID `9702754414644deba5cb4ed3e9f33594`. The plan shows UUIDs as `<uuid>` placeholders — replace each with a freshly generated one.

**Credentials:** `scripts/.env` already exists (gitignored) with `ZABBIX_URL=http://zabbix.example.local`-style real values. Do not print or commit it.

---

## Task 1: Repo scaffolding — import script, validator, .env.example, LICENSE

**Files:**
- Create: `scripts/import_templates.py`
- Create: `scripts/validate.py`
- Create: `scripts/.env.example`
- Create: `LICENSE`
- Create: `templates/mqtt/.gitkeep`

- [ ] **Step 1: Create `scripts/.env.example`**

```
# Copy to .env and fill in. .env is gitignored — never commit real credentials.

# Zabbix frontend URL. /api_jsonrpc.php is appended automatically if omitted.
ZABBIX_URL=http://zabbix.example.local

# Zabbix API token: Users -> API tokens -> Create (needs template/host write perms).
ZABBIX_TOKEN=your-api-token-here
```

- [ ] **Step 2: Create `scripts/import_templates.py`**

Stdlib-only. Dependency order: common base first, then linked device templates, then the standalone bridge. Full content:

```python
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
```

- [ ] **Step 3: Create `scripts/validate.py` (the static test harness)**

```python
#!/usr/bin/env python3
"""Static validator for the Zigbee Zabbix template YAML. Catches the schema-rule
violations that a live 7.4 import rejects, before hitting the network.

Run: python3 scripts/validate.py
Exit 0 = all checks pass; exit 1 = a violation (message names the file/rule).
"""
import glob
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_GROUP = "9702754414644deba5cb4ed3e9f33594"  # Templates/IoT — intentionally shared


def main():
    files = sorted(glob.glob(os.path.join(REPO, "templates", "**", "*.yaml"), recursive=True))
    if not files:
        print("no template YAML found under templates/", file=sys.stderr)
        return 1
    allu = []
    problems = []
    for f in files:
        txt = open(f, encoding="utf-8").read()
        rel = os.path.relpath(f, REPO)
        u = [x.lower() for x in re.findall(r"uuid:\s*([0-9a-f]{32})", txt)]
        for x in u:
            if not (x[12] == "4" and x[16] in "89ab"):
                problems.append("%s: uuid not valid v4: %s" % (rel, x))
        if "\t" in txt:
            problems.append("%s: tab character present (use 2-space indent)" % rel)
        if re.search(r"^  value_maps:", txt, re.M):
            problems.append("%s: value_maps at root (must be valuemaps: inside template)" % rel)
        if re.search(r"^      triggers:", txt, re.M):
            problems.append("%s: triggers inside template (must be root-level)" % rel)
        allu += u
    dupes = {k for k, v in Counter(allu).items() if v > 1}
    unexpected = dupes - {SHARED_GROUP}
    if unexpected:
        problems.append("cross-file duplicate UUIDs: %s" % ", ".join(sorted(unexpected)))
    if problems:
        for p in problems:
            print("FAIL  " + p, file=sys.stderr)
        return 1
    print("OK  %d template file(s) pass static validation." % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Create `LICENSE` (MIT, no personal name — public repo)**

```
MIT License

Copyright (c) 2026 zabbix-zigbee contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: Create empty `templates/mqtt/.gitkeep`** (so the dir exists before templates land)

```
```

- [ ] **Step 6: Verify import script parses and dry-run lists the 5 files**

Run: `python3 scripts/import_templates.py --dry-run`
Expected: exits 2 with "file(s) not found" (templates not built yet) — this confirms the script runs and the DEFAULT_FILES list is wired. FAIL-state check.

- [ ] **Step 7: Commit**

```bash
git add scripts/import_templates.py scripts/validate.py scripts/.env.example LICENSE templates/mqtt/.gitkeep
git commit -m "feat: repo scaffolding — import script, static validator, license"
```

---

## Task 2: Common base template

**Files:**
- Create: `templates/mqtt/zigbee2mqtt_common_by_mqtt.yaml`

Template `Zigbee2MQTT common by MQTT`. Master `mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]` (`value_type: TEXT`, `history: '1h'` so `nodata()` can read it). Dependent items: `linkquality`, `battery`, firmware `update_available` (JS). Value maps `Zigbee boolean` (0/1 → No/Yes). Macros: `{$Z2M.SESSION}` (default `zigbee`), `{$Z2M.TOPIC}` (empty, REQUIRED), `{$Z2M.DATA.TIMEOUT}` (default `30m`), `{$Z2M.BATTERY.MIN}` (default `15`), `{$Z2M.LINKQUALITY.MIN}` (default `20`). Triggers (ROOT level): battery low, weak link, no data.

- [ ] **Step 1: Write the template YAML**

Generate 1 group UUID (use the shared constant), 1 template UUID, 1 UUID per item, 1 per valuemap, 1 per trigger — all fresh except the group. Full content (replace every `<uuid>` with a fresh `python3 -c "import uuid;print(uuid.uuid4().hex)"`):

```yaml
zabbix_export:
  version: '7.4'
  template_groups:
    - uuid: 9702754414644deba5cb4ed3e9f33594
      name: Templates/IoT
  templates:
    - uuid: <uuid>
      template: 'Zigbee2MQTT common by MQTT'
      name: 'Zigbee2MQTT common by MQTT'
      description: |
        Common base for zigbee2mqtt (z2m) devices monitored over MQTT via the
        Zabbix agent 2 MQTT plugin. z2m publishes the entire device state as one
        JSON blob to z2m/<device>; this base defines the master mqtt.get item and
        the device-agnostic dependents (linkquality, battery, firmware update).
        Link this from a device template that adds the device's own metrics.

        Per host (usually inherited via the linking template):
          {$Z2M.TOPIC}   = FULL topic, e.g. z2m/<device-name> (REQUIRED, verbatim)
          {$Z2M.SESSION} = agent 2 MQTT session name (default 'zigbee');
                           broker URL + creds live on the agent, not here.
        NOTE: device topics are NOT retained, so items populate on the next
        device change after the agent subscribes (not immediately).
      groups:
        - name: Templates/IoT
      macros:
        - macro: '{$Z2M.SESSION}'
          value: 'zigbee'
          description: 'Zabbix agent 2 MQTT named session (Plugins.MQTT.Sessions.<name>.*). Broker URL + credentials live on the agent, not here.'
        - macro: '{$Z2M.TOPIC}'
          value: ''
          description: 'REQUIRED. FULL device MQTT topic = <base_topic>/<device-name>, e.g. z2m/<device-name>. Passed verbatim. Set per host.'
        - macro: '{$Z2M.DATA.TIMEOUT}'
          value: '30m'
          description: 'nodata() window for the master item; if no message arrives within this the device is considered silent.'
        - macro: '{$Z2M.BATTERY.MIN}'
          value: '15'
          description: 'Battery percent below which a low-battery warning fires.'
        - macro: '{$Z2M.LINKQUALITY.MIN}'
          value: '20'
          description: 'Zigbee LQI below which the link is considered weak (0-255 scale).'
      items:
        - uuid: <uuid>
          name: 'Device: Raw state (JSON)'
          type: ZABBIX_ACTIVE
          key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          delay: '0'
          history: '1h'
          trends: '0'
          value_type: TEXT
          description: 'Master item: full JSON payload from z2m/<device>. Dependents parse fields from this. history=1h so nodata() liveness can read it.'
          tags:
            - tag: component
              value: raw
        - uuid: <uuid>
          name: 'Link quality (LQI)'
          type: DEPENDENT
          key: 'z2m.linkquality'
          value_type: UNSIGNED
          units: '!lqi'
          description: 'Zigbee link quality indicator (0-255). Kept with history/trends for long-term signal statistics.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.linkquality'
          tags:
            - tag: component
              value: network
        - uuid: <uuid>
          name: 'Battery'
          type: DEPENDENT
          key: 'z2m.battery'
          value_type: UNSIGNED
          units: '%'
          description: 'Remaining battery (%). Empty on mains-powered devices (no battery field) — that is expected and the low-battery trigger will not fire.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.battery'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1h'
          tags:
            - tag: component
              value: battery
        - uuid: <uuid>
          name: 'Firmware update available'
          type: DEPENDENT
          key: 'z2m.update_available'
          value_type: UNSIGNED
          description: '1 if a firmware update is pending (update.state=available OR installed_version != latest_version), else 0. Missing update object => 0.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var u = JSON.parse(value).update;
                  if (!u) return 0;
                  if (u.state === "available") return 1;
                  if (u.installed_version != null && u.latest_version != null
                      && u.installed_version !== u.latest_version) return 1;
                  return 0;
          valuemap:
            name: 'Zigbee boolean'
          tags:
            - tag: component
              value: firmware
      valuemaps:
        - uuid: <uuid>
          name: 'Zigbee boolean'
          mappings:
            - value: '0'
              newvalue: 'No'
            - value: '1'
              newvalue: 'Yes'
        - uuid: <uuid>
          name: 'Zigbee state'
          mappings:
            - value: '0'
              newvalue: 'OFF'
            - value: '1'
              newvalue: 'ON'
  triggers:
    - uuid: <uuid>
      expression: 'last(/Zigbee2MQTT common by MQTT/z2m.battery)<{$Z2M.BATTERY.MIN} and last(/Zigbee2MQTT common by MQTT/z2m.battery)>0'
      name: 'Zigbee: Low battery (<{$Z2M.BATTERY.MIN}%)'
      priority: WARNING
      description: 'Battery dropped below the threshold. The >0 guard avoids firing on mains devices that report battery 0/empty.'
    - uuid: <uuid>
      expression: 'max(/Zigbee2MQTT common by MQTT/z2m.linkquality,15m)<{$Z2M.LINKQUALITY.MIN}'
      name: 'Zigbee: Weak link quality (<{$Z2M.LINKQUALITY.MIN} LQI)'
      priority: INFO
      description: 'LQI stayed below the threshold for 15m; the device may be far from a router/coordinator. INFO — primarily a statistic.'
    - uuid: <uuid>
      expression: 'nodata(/Zigbee2MQTT common by MQTT/mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}],{$Z2M.DATA.TIMEOUT})=1'
      name: 'Zigbee: No data from device'
      priority: WARNING
      description: 'No MQTT message received within {$Z2M.DATA.TIMEOUT}. The device may be offline, or (for battery devices) simply quiet — tune the macro per device class.'
```

- [ ] **Step 2: Run static validation (expect PASS)**

Run: `python3 scripts/validate.py`
Expected: `OK  1 template file(s) pass static validation.` If it FAILs on UUIDv4, regenerate the offending UUID.

- [ ] **Step 3: Live import (authoritative check)**

Run: `python3 scripts/import_templates.py templates/mqtt/zigbee2mqtt_common_by_mqtt.yaml`
Expected: `OK    zigbee2mqtt_common_by_mqtt.yaml`. If FAIL, the error message is the first schema problem — fix and re-run (iterate; the importer stops at the first error).

- [ ] **Step 4: Commit**

```bash
git add templates/mqtt/zigbee2mqtt_common_by_mqtt.yaml
git commit -m "feat: common base template (linkquality, battery, firmware, liveness)"
```

---

## Task 3: SONOFF SWV-ZF2 water valve template (the showcase)

**Files:**
- Create: `templates/mqtt/sonoff_swv_zf2_water_valve_by_mqtt.yaml`

Template `SONOFF SWV-ZF2 water valve by MQTT`, links the base. Adds: valve state ch1/ch2 (map), live run duration ch1/ch2, live volume, hour volume, per-event water litres ch1/ch2 (JS-guarded on completed events), event total (JS sum), valve abnormal state (map), child lock (map), firmware update state (CHAR), model/vendor inventory. Macro `{$Z2M.MODEL}` = `SWV-ZF2`. Triggers: valve abnormal (HIGH).

The water-accumulation JS emits litres ONLY on a newly-completed event, else returns `null` which with `DISCARD_UNCHANGED` semantics is achieved by throwing to skip. Zabbix JS preprocessing: returning a value stores it; to skip storing, use a second `DISCARD_UNCHANGED_HEARTBEAT` won't help (that dedups identical values). The reliable approach: JS emits a compound string `"<actual_end_time>|<litres>"`, followed by `DISCARD_UNCHANGED` (no heartbeat) so an unchanged completed-event is dropped; then a final JS splits off the litres. **This two-item chain is the mechanism the spec flagged for live verification — validate it below.**

- [ ] **Step 1: Write the template YAML**

Replace every `<uuid>` with a fresh UUIDv4. Full content:

```yaml
zabbix_export:
  version: '7.4'
  template_groups:
    - uuid: 9702754414644deba5cb4ed3e9f33594
      name: Templates/IoT
  templates:
    - uuid: <uuid>
      template: 'SONOFF SWV-ZF2 water valve by MQTT'
      name: 'SONOFF SWV-ZF2 water valve by MQTT'
      description: |
        SONOFF SWV-ZF2 dual-channel Zigbee smart water valve, over MQTT (agent 2
        MQTT plugin). Links "Zigbee2MQTT common by MQTT" for battery/linkquality/
        firmware/liveness; adds irrigation metrics: valve state, run duration and
        live volume per channel, per-event water litres (channels + summed) and
        valve abnormal state. Import the common base FIRST. Fits z2m friendly-name
        e.g. garden-pump. Set {$Z2M.TOPIC}=z2m/<device-name> on the host.
      templates:
        - name: 'Zigbee2MQTT common by MQTT'
      groups:
        - name: Templates/IoT
      macros:
        - macro: '{$Z2M.MODEL}'
          value: 'SWV-ZF2'
          description: 'Device model, fed to host inventory Model.'
      items:
        - uuid: <uuid>
          name: 'Valve 1: State'
          type: DEPENDENT
          key: 'z2m.valve.state[1]'
          value_type: UNSIGNED
          description: 'Channel 1 valve open state (1=ON/open).'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.state_1'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "ON" ? 1 : 0;'
          valuemap:
            name: 'Zigbee state'
          tags:
            - tag: component
              value: valve
        - uuid: <uuid>
          name: 'Valve 2: State'
          type: DEPENDENT
          key: 'z2m.valve.state[2]'
          value_type: UNSIGNED
          description: 'Channel 2 valve open state (1=ON/open).'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.state_2'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "ON" ? 1 : 0;'
          valuemap:
            name: 'Zigbee state'
          tags:
            - tag: component
              value: valve
        - uuid: <uuid>
          name: 'Valve 1: Live run duration'
          type: DEPENDENT
          key: 'z2m.valve.duration[1]'
          value_type: UNSIGNED
          units: min
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.real_time_irrigation_duration_1'
          tags:
            - tag: component
              value: valve
        - uuid: <uuid>
          name: 'Valve 2: Live run duration'
          type: DEPENDENT
          key: 'z2m.valve.duration[2]'
          value_type: UNSIGNED
          units: min
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.real_time_irrigation_duration_2'
          tags:
            - tag: component
              value: valve
        - uuid: <uuid>
          name: 'Live irrigation volume'
          type: DEPENDENT
          key: 'z2m.valve.rt_volume'
          value_type: FLOAT
          units: L
          description: 'real_time_irrigation_volume — live volume during an active run.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.real_time_irrigation_volume'
          tags:
            - tag: component
              value: water
        - uuid: <uuid>
          name: 'Irrigation volume this hour'
          type: DEPENDENT
          key: 'z2m.valve.hour_volume'
          value_type: FLOAT
          units: L
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.hour_irrigation_volume'
          tags:
            - tag: component
              value: water
        - uuid: <uuid>
          name: 'Valve 1: Water used per completed event'
          type: DEPENDENT
          key: 'z2m.valve.event_litres[1]'
          value_type: FLOAT
          units: L
          description: 'Litres delivered, emitted ONLY once per newly-completed event (schedule_status=end, new actual_end_time). Feeds sum() for litres/day. DISCARD_UNCHANGED drops republished identical events.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var s = JSON.parse(value).irrigation_schedule_status_1;
                  if (!s || s.schedule_status !== "end") throw "no completed event";
                  return s.actual_end_time + "|" + s.actual_irrigation_amount;
            - type: DISCARD_UNCHANGED
              parameters:
                - ''
            - type: JAVASCRIPT
              parameters:
                - 'return parseFloat(value.split("|")[1]);'
          tags:
            - tag: component
              value: water
        - uuid: <uuid>
          name: 'Valve 2: Water used per completed event'
          type: DEPENDENT
          key: 'z2m.valve.event_litres[2]'
          value_type: FLOAT
          units: L
          description: 'Litres delivered on channel 2, emitted once per newly-completed event. See channel 1 for mechanism.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var s = JSON.parse(value).irrigation_schedule_status_2;
                  if (!s || s.schedule_status !== "end") throw "no completed event";
                  return s.actual_end_time + "|" + s.actual_irrigation_amount;
            - type: DISCARD_UNCHANGED
              parameters:
                - ''
            - type: JAVASCRIPT
              parameters:
                - 'return parseFloat(value.split("|")[1]);'
          tags:
            - tag: component
              value: water
        - uuid: <uuid>
          name: 'Water used per completed event (both channels)'
          type: DEPENDENT
          key: 'z2m.valve.event_litres_total'
          value_type: FLOAT
          units: L
          description: 'Sum of channels 1+2 litres, emitted once per newly-completed event on either channel. Keyed on the pair of actual_end_times so republished payloads are discarded.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var d = JSON.parse(value);
                  var s1 = d.irrigation_schedule_status_1 || {};
                  var s2 = d.irrigation_schedule_status_2 || {};
                  var e1 = s1.schedule_status === "end";
                  var e2 = s2.schedule_status === "end";
                  if (!e1 && !e2) throw "no completed event";
                  var l1 = e1 ? (s1.actual_irrigation_amount || 0) : 0;
                  var l2 = e2 ? (s2.actual_irrigation_amount || 0) : 0;
                  return (s1.actual_end_time||"") + "/" + (s2.actual_end_time||"") + "|" + (l1 + l2);
            - type: DISCARD_UNCHANGED
              parameters:
                - ''
            - type: JAVASCRIPT
              parameters:
                - 'return parseFloat(value.split("|")[1]);'
          tags:
            - tag: component
              value: water
        - uuid: <uuid>
          name: 'Valve abnormal state'
          type: DEPENDENT
          key: 'z2m.valve.abnormal'
          value_type: UNSIGNED
          description: 'valve_abnormal_state: 0=normal, 1=abnormal (leak/shortage/fault).'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.valve_abnormal_state'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "normal" ? 0 : 1;'
          valuemap:
            name: 'Zigbee boolean'
          tags:
            - tag: component
              value: fault
        - uuid: <uuid>
          name: 'Child lock'
          type: DEPENDENT
          key: 'z2m.valve.child_lock'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.child_lock'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "LOCK" ? 1 : 0;'
          valuemap:
            name: 'Zigbee boolean'
          tags:
            - tag: component
              value: config
        - uuid: <uuid>
          name: 'Firmware update state'
          type: DEPENDENT
          key: 'z2m.valve.update_state'
          value_type: CHAR
          description: 'update.state: idle/scheduled/available/updating.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.update.state'
          tags:
            - tag: component
              value: firmware
        - uuid: <uuid>
          name: 'Model'
          type: DEPENDENT
          key: 'z2m.valve.model'
          value_type: CHAR
          description: 'Constant device model from {$Z2M.MODEL}; feeds host inventory Model.'
          inventory_link: MODEL
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - 'return "{$Z2M.MODEL}";'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1d'
          tags:
            - tag: component
              value: inventory
        - uuid: <uuid>
          name: 'Vendor'
          type: DEPENDENT
          key: 'z2m.valve.vendor'
          value_type: CHAR
          description: 'Constant "SONOFF"; feeds host inventory Vendor.'
          inventory_link: VENDOR
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - 'return "SONOFF";'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1d'
          tags:
            - tag: component
              value: inventory
  triggers:
    - uuid: <uuid>
      expression: 'last(/SONOFF SWV-ZF2 water valve by MQTT/z2m.valve.abnormal)=1'
      name: 'Zigbee valve: Abnormal state (leak/shortage/fault)'
      priority: HIGH
      description: 'valve_abnormal_state is not "normal" — possible water leak, shortage, or valve fault.'
```

- [ ] **Step 2: Static validation (expect PASS)**

Run: `python3 scripts/validate.py`
Expected: `OK  2 template file(s) pass static validation.`

- [ ] **Step 3: Live import (base must already be imported from Task 2)**

Run: `python3 scripts/import_templates.py templates/mqtt/sonoff_swv_zf2_water_valve_by_mqtt.yaml`
Expected: `OK`. If it FAILs with a linked-template error, confirm Task 2's base imported first. If it FAILs on the `DISCARD_UNCHANGED` preprocessing step params, that is the flagged mechanism — see Step 4.

- [ ] **Step 4: Verify the water-accumulation mechanism against 7.4**

The `DISCARD_UNCHANGED` step takes NO parameters in 7.4 export YAML (empty string param as written). Confirm the import accepted the three-step chain (JS → DISCARD_UNCHANGED → JS) on `z2m.valve.event_litres[1]`. Verify in the UI: item `z2m.valve.event_litres[1]` → Preprocessing tab shows the three steps. If 7.4 rejects `DISCARD_UNCHANGED` on a dependent item or the param form, fall back to a single JS step that persists last-seen `actual_end_time` — but 7.4 has no cross-invocation JS state, so the DISCARD_UNCHANGED chain is the correct approach; only its exact param encoding may need adjustment. Record the working form in `docs/zabbix-7.4-template-reference.md` (created in Task 6).

- [ ] **Step 5: Commit**

```bash
git add templates/mqtt/sonoff_swv_zf2_water_valve_by_mqtt.yaml
git commit -m "feat: SONOFF SWV-ZF2 water valve template with per-event litres accumulation"
```

---

## Task 4: Tuya TS011F smart plug template

**Files:**
- Create: `templates/mqtt/tuya_ts011f_smart_plug_by_mqtt.yaml`

Template `Tuya TS011F smart plug by MQTT`, links the base. Fields (confirmed live): `state` (map), `power` (W), `current` (A), `voltage` (V), `energy` (kWh, cumulative counter), `child_lock` (map), `update.state`. Macro `{$Z2M.POWER.MAX}` (default `3680`). Trigger: high power (WARNING).

- [ ] **Step 1: Write the template YAML** (replace every `<uuid>` fresh)

```yaml
zabbix_export:
  version: '7.4'
  template_groups:
    - uuid: 9702754414644deba5cb4ed3e9f33594
      name: Templates/IoT
  templates:
    - uuid: <uuid>
      template: 'Tuya TS011F smart plug by MQTT'
      name: 'Tuya TS011F smart plug by MQTT'
      description: |
        Metered Zigbee smart plug (Tuya TS011F; e.g. Nous A7Z,
        manufacturer _TZ3008_reatplte) over MQTT. Links "Zigbee2MQTT common by
        MQTT" for linkquality/firmware/liveness; adds on/off state and power
        metering (power, current, voltage, cumulative energy). Fits z2m
        friendly-names e.g. base-plug-1, base-plug-2, living-plug. Import the
        common base FIRST. Mains-powered (Router) — battery item stays empty.
      templates:
        - name: 'Zigbee2MQTT common by MQTT'
      groups:
        - name: Templates/IoT
      macros:
        - macro: '{$Z2M.POWER.MAX}'
          value: '3680'
          description: 'Active-power warning threshold, watts (default ~16 A * 230 V).'
      items:
        - uuid: <uuid>
          name: 'State'
          type: DEPENDENT
          key: 'z2m.plug.state'
          value_type: UNSIGNED
          description: 'Relay on/off (1=ON).'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.state'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "ON" ? 1 : 0;'
          valuemap:
            name: 'Zigbee state'
          tags:
            - tag: component
              value: switch
        - uuid: <uuid>
          name: 'Power'
          type: DEPENDENT
          key: 'z2m.plug.power'
          value_type: FLOAT
          units: W
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.power'
          tags:
            - tag: component
              value: power
        - uuid: <uuid>
          name: 'Current'
          type: DEPENDENT
          key: 'z2m.plug.current'
          value_type: FLOAT
          units: A
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.current'
          tags:
            - tag: component
              value: power
        - uuid: <uuid>
          name: 'Voltage'
          type: DEPENDENT
          key: 'z2m.plug.voltage'
          value_type: FLOAT
          units: V
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.voltage'
          tags:
            - tag: component
              value: power
        - uuid: <uuid>
          name: 'Energy (cumulative)'
          type: DEPENDENT
          key: 'z2m.plug.energy'
          value_type: FLOAT
          units: kWh
          description: 'Cumulative consumed energy (monotonic device counter). Daily/weekly use = change() over this on the dashboard.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.energy'
          tags:
            - tag: component
              value: energy
        - uuid: <uuid>
          name: 'Child lock'
          type: DEPENDENT
          key: 'z2m.plug.child_lock'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.child_lock'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "LOCK" ? 1 : 0;'
          valuemap:
            name: 'Zigbee boolean'
          tags:
            - tag: component
              value: config
        - uuid: <uuid>
          name: 'Firmware update state'
          type: DEPENDENT
          key: 'z2m.plug.update_state'
          value_type: CHAR
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.update.state'
          tags:
            - tag: component
              value: firmware
  triggers:
    - uuid: <uuid>
      expression: 'last(/Tuya TS011F smart plug by MQTT/z2m.plug.power)>{$Z2M.POWER.MAX}'
      name: 'Zigbee plug: High power draw (>{$Z2M.POWER.MAX} W)'
      priority: WARNING
      description: 'Active power exceeded the threshold.'
```

- [ ] **Step 2: Static validation** — Run: `python3 scripts/validate.py` — Expected: `OK  3 template file(s) pass static validation.`

- [ ] **Step 3: Live import** — Run: `python3 scripts/import_templates.py templates/mqtt/tuya_ts011f_smart_plug_by_mqtt.yaml` — Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add templates/mqtt/tuya_ts011f_smart_plug_by_mqtt.yaml
git commit -m "feat: Tuya TS011F smart plug template (state + power metering)"
```

---

## Task 5: Tuya TS0201 temperature/humidity sensor template

**Files:**
- Create: `templates/mqtt/tuya_ts0201_temp_humidity_sensor_by_mqtt.yaml`

Template `Tuya TS0201 temp/humidity sensor by MQTT`, links the base. Fields (confirmed live): `temperature` (°C), `humidity` (%). Battery/linkquality inherited. Macros `{$Z2M.TEMP.MAX}` (default `40`), `{$Z2M.TEMP.MIN}` (default `-10`). Triggers: high temp, low temp (both WARNING, status DISABLED by default since thresholds are site-specific).

- [ ] **Step 1: Write the template YAML** (replace every `<uuid>` fresh)

```yaml
zabbix_export:
  version: '7.4'
  template_groups:
    - uuid: 9702754414644deba5cb4ed3e9f33594
      name: Templates/IoT
  templates:
    - uuid: <uuid>
      template: 'Tuya TS0201 temp/humidity sensor by MQTT'
      name: 'Tuya TS0201 temp/humidity sensor by MQTT'
      description: |
        Zigbee temperature + humidity sensor (Tuya TS0201; e.g. TH09Z,
        manufacturer _TZ3000_yupc0pb7) over MQTT. Links "Zigbee2MQTT common by
        MQTT" for battery/linkquality/firmware/liveness; adds temperature and
        humidity. Fits z2m friendly-name e.g. base-out. Import the common base
        FIRST. Battery-powered — battery + low-battery trigger come from the base.
      templates:
        - name: 'Zigbee2MQTT common by MQTT'
      groups:
        - name: Templates/IoT
      macros:
        - macro: '{$Z2M.TEMP.MAX}'
          value: '40'
          description: 'High-temperature warning threshold (°C). Trigger DISABLED by default — site-specific.'
        - macro: '{$Z2M.TEMP.MIN}'
          value: '-10'
          description: 'Low-temperature warning threshold (°C). Trigger DISABLED by default — site-specific.'
      items:
        - uuid: <uuid>
          name: 'Temperature'
          type: DEPENDENT
          key: 'z2m.sensor.temperature'
          value_type: FLOAT
          units: °C
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.temperature'
          tags:
            - tag: component
              value: climate
        - uuid: <uuid>
          name: 'Humidity'
          type: DEPENDENT
          key: 'z2m.sensor.humidity'
          value_type: FLOAT
          units: '%'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.humidity'
          tags:
            - tag: component
              value: climate
  triggers:
    - uuid: <uuid>
      expression: 'last(/Tuya TS0201 temp/humidity sensor by MQTT/z2m.sensor.temperature)>{$Z2M.TEMP.MAX}'
      name: 'Zigbee sensor: High temperature (>{$Z2M.TEMP.MAX} °C)'
      priority: WARNING
      status: DISABLED
      description: 'Temperature above the site-specific threshold. Disabled by default — enable and tune per location.'
    - uuid: <uuid>
      expression: 'last(/Tuya TS0201 temp/humidity sensor by MQTT/z2m.sensor.temperature)<{$Z2M.TEMP.MIN}'
      name: 'Zigbee sensor: Low temperature (<{$Z2M.TEMP.MIN} °C)'
      priority: WARNING
      status: DISABLED
      description: 'Temperature below the site-specific threshold (e.g. frost risk). Disabled by default — enable and tune per location.'
```

- [ ] **Step 2: Static validation** — Run: `python3 scripts/validate.py` — Expected: `OK  4 template file(s) pass static validation.`

- [ ] **Step 3: Live import** — Run: `python3 scripts/import_templates.py templates/mqtt/tuya_ts0201_temp_humidity_sensor_by_mqtt.yaml` — Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add templates/mqtt/tuya_ts0201_temp_humidity_sensor_by_mqtt.yaml
git commit -m "feat: Tuya TS0201 temperature/humidity sensor template"
```

---

## Task 6: Zigbee2MQTT bridge template + reference doc

**Files:**
- Create: `templates/mqtt/zigbee2mqtt_bridge_by_mqtt.yaml`
- Create: `docs/zabbix-7.4-template-reference.md`

Template `Zigbee2MQTT bridge by MQTT`, STANDALONE (no base link). Three masters: `.../state`, `.../health`, `.../info` (retained). Items per the spec's bridge table: bridge online (map), load avg 1m, host mem %, process uptime, process mem, mqtt connected, mqtt queued, mqtt published, total leaves (JS sum), total msgs/sec (JS sum), device count (JS), channel, version, pan_id. Macros: `{$Z2M.SESSION}` (default `zigbee`), `{$Z2M.BRIDGE.TOPIC}` (default `z2m/bridge`), `{$Z2M.BRIDGE.MEM.MAX}` (default `90`), `{$Z2M.BRIDGE.DATA.TIMEOUT}` (default `30m`). Triggers: bridge offline (HIGH), high host memory (WARNING), MQTT disconnected (WARNING), device left network (WARNING).

- [ ] **Step 1: Write the template YAML** (replace every `<uuid>` fresh)

```yaml
zabbix_export:
  version: '7.4'
  template_groups:
    - uuid: 9702754414644deba5cb4ed3e9f33594
      name: Templates/IoT
  templates:
    - uuid: <uuid>
      template: 'Zigbee2MQTT bridge by MQTT'
      name: 'Zigbee2MQTT bridge by MQTT'
      description: |
        The zigbee2mqtt gateway itself, monitored as its own Zabbix host — the
        "master host" of the Zigbee fleet. Standalone (does NOT link the common
        base; the bridge is not a Zigbee end device). Three retained master
        topics: bridge/state, bridge/health, bridge/info — items populate
        immediately on subscribe. bridge/health publishes every health.interval
        minutes (z2m default 10). The bridge-offline trigger is the highest-value
        alert: if the gateway dies, every device silently goes stale.
        Set {$Z2M.BRIDGE.TOPIC}=<base_topic>/bridge (default z2m/bridge).
      groups:
        - name: Templates/IoT
      macros:
        - macro: '{$Z2M.SESSION}'
          value: 'zigbee'
          description: 'Zabbix agent 2 MQTT named session. Broker URL + creds live on the agent.'
        - macro: '{$Z2M.BRIDGE.TOPIC}'
          value: 'z2m/bridge'
          description: 'FULL bridge topic root = <base_topic>/bridge. Default z2m/bridge.'
        - macro: '{$Z2M.BRIDGE.MEM.MAX}'
          value: '90'
          description: 'Host memory percent above which a warning fires.'
        - macro: '{$Z2M.BRIDGE.DATA.TIMEOUT}'
          value: '30m'
          description: 'nodata() window for bridge/health (publishes ~every 10 min).'
      items:
        - uuid: <uuid>
          name: 'Bridge: Raw state'
          type: ZABBIX_ACTIVE
          key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/state]'
          delay: '0'
          history: '1h'
          trends: '0'
          value_type: TEXT
          description: 'Master: retained bridge/state JSON, e.g. {"state":"online"}.'
          tags:
            - tag: component
              value: raw
        - uuid: <uuid>
          name: 'Bridge: Online'
          type: DEPENDENT
          key: 'z2m.bridge.online'
          value_type: UNSIGNED
          description: '1 when gateway state is online.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/state]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.state'
            - type: JAVASCRIPT
              parameters:
                - 'return value === "online" ? 1 : 0;'
          valuemap:
            name: 'Zigbee online'
          tags:
            - tag: component
              value: availability
        - uuid: <uuid>
          name: 'Bridge: Raw health'
          type: ZABBIX_ACTIVE
          key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          delay: '0'
          history: '1h'
          trends: '0'
          value_type: TEXT
          description: 'Master: retained bridge/health JSON (os/process/mqtt/devices stats).'
          tags:
            - tag: component
              value: raw
        - uuid: <uuid>
          name: 'Host: Load average (1m)'
          type: DEPENDENT
          key: 'z2m.bridge.load1'
          value_type: FLOAT
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.os.load_average[0]'
          tags:
            - tag: component
              value: host
        - uuid: <uuid>
          name: 'Host: Memory used'
          type: DEPENDENT
          key: 'z2m.bridge.host_mem_pct'
          value_type: FLOAT
          units: '%'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.os.memory_percent'
          tags:
            - tag: component
              value: host
        - uuid: <uuid>
          name: 'Process: Uptime'
          type: DEPENDENT
          key: 'z2m.bridge.uptime'
          value_type: UNSIGNED
          units: s
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.process.uptime_sec'
          tags:
            - tag: component
              value: process
        - uuid: <uuid>
          name: 'Process: Memory used'
          type: DEPENDENT
          key: 'z2m.bridge.proc_mem'
          value_type: FLOAT
          units: '!MB'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.process.memory_used_mb'
          tags:
            - tag: component
              value: process
        - uuid: <uuid>
          name: 'MQTT: Connected'
          type: DEPENDENT
          key: 'z2m.bridge.mqtt_connected'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.mqtt.connected'
            - type: BOOL_TO_DECIMAL
              parameters:
                - ''
          valuemap:
            name: 'Zigbee boolean'
          tags:
            - tag: component
              value: availability
        - uuid: <uuid>
          name: 'MQTT: Queued'
          type: DEPENDENT
          key: 'z2m.bridge.mqtt_queued'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.mqtt.queued'
          tags:
            - tag: component
              value: mqtt
        - uuid: <uuid>
          name: 'MQTT: Published (total)'
          type: DEPENDENT
          key: 'z2m.bridge.mqtt_published'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.mqtt.published'
          tags:
            - tag: component
              value: mqtt
        - uuid: <uuid>
          name: 'Devices: Total leaves'
          type: DEPENDENT
          key: 'z2m.bridge.total_leaves'
          value_type: UNSIGNED
          description: 'Sum of leave_count across all devices; >0 means a device left the network.'
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var d = JSON.parse(value).devices || {};
                  var n = 0;
                  for (var k in d) { n += (d[k].leave_count || 0); }
                  return n;
          tags:
            - tag: component
              value: network
        - uuid: <uuid>
          name: 'Devices: Total messages/sec'
          type: DEPENDENT
          key: 'z2m.bridge.total_msgs_per_sec'
          value_type: FLOAT
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - |
                  var d = JSON.parse(value).devices || {};
                  var s = 0;
                  for (var k in d) { s += (d[k].messages_per_sec || 0); }
                  return s;
          tags:
            - tag: component
              value: network
        - uuid: <uuid>
          name: 'Devices: Count'
          type: DEPENDENT
          key: 'z2m.bridge.device_count'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health]'
          preprocessing:
            - type: JAVASCRIPT
              parameters:
                - 'return Object.keys(JSON.parse(value).devices || {}).length;'
          tags:
            - tag: component
              value: network
        - uuid: <uuid>
          name: 'Bridge: Raw info'
          type: ZABBIX_ACTIVE
          key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/info]'
          delay: '0'
          history: '1h'
          trends: '0'
          value_type: TEXT
          description: 'Master: retained bridge/info JSON (config, version, coordinator).'
          tags:
            - tag: component
              value: raw
        - uuid: <uuid>
          name: 'Zigbee channel'
          type: DEPENDENT
          key: 'z2m.bridge.channel'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/info]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.config.advanced.channel'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1d'
          tags:
            - tag: component
              value: inventory
        - uuid: <uuid>
          name: 'z2m version'
          type: DEPENDENT
          key: 'z2m.bridge.version'
          value_type: CHAR
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/info]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.version'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1d'
          tags:
            - tag: component
              value: inventory
        - uuid: <uuid>
          name: 'Zigbee PAN ID'
          type: DEPENDENT
          key: 'z2m.bridge.pan_id'
          value_type: UNSIGNED
          master_item:
            key: 'mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/info]'
          preprocessing:
            - type: JSONPATH
              parameters:
                - '$.config.advanced.pan_id'
            - type: DISCARD_UNCHANGED_HEARTBEAT
              parameters:
                - '1d'
          tags:
            - tag: component
              value: inventory
      valuemaps:
        - uuid: <uuid>
          name: 'Zigbee online'
          mappings:
            - value: '0'
              newvalue: 'Offline'
            - value: '1'
              newvalue: 'Online'
        - uuid: <uuid>
          name: 'Zigbee boolean'
          mappings:
            - value: '0'
              newvalue: 'No'
            - value: '1'
              newvalue: 'Yes'
  triggers:
    - uuid: <uuid>
      expression: 'last(/Zigbee2MQTT bridge by MQTT/z2m.bridge.online)=0'
      name: 'Zigbee2MQTT: Bridge OFFLINE (whole network down)'
      priority: HIGH
      description: 'The z2m gateway reported offline. Every Zigbee device is now unreachable/stale — this is the single liveness signal for the fleet.'
    - uuid: <uuid>
      expression: 'nodata(/Zigbee2MQTT bridge by MQTT/mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/health],{$Z2M.BRIDGE.DATA.TIMEOUT})=1'
      name: 'Zigbee2MQTT: No bridge health data'
      priority: WARNING
      description: 'No bridge/health message within the timeout; z2m may be stopped or the agent lost the broker.'
    - uuid: <uuid>
      expression: 'min(/Zigbee2MQTT bridge by MQTT/z2m.bridge.host_mem_pct,15m)>{$Z2M.BRIDGE.MEM.MAX}'
      name: 'Zigbee2MQTT: High host memory (>{$Z2M.BRIDGE.MEM.MAX}%)'
      priority: WARNING
      description: 'Host memory stayed above the threshold for 15m.'
    - uuid: <uuid>
      expression: 'last(/Zigbee2MQTT bridge by MQTT/z2m.bridge.mqtt_connected)=0'
      name: 'Zigbee2MQTT: MQTT disconnected'
      priority: WARNING
      description: 'z2m lost its connection to the MQTT broker.'
    - uuid: <uuid>
      expression: 'change(/Zigbee2MQTT bridge by MQTT/z2m.bridge.total_leaves)>0'
      name: 'Zigbee2MQTT: A device left the network'
      priority: WARNING
      manual_close: 'YES'
      description: 'Total device leave_count increased — a device dropped off the Zigbee network.'
```

- [ ] **Step 2: Static validation** — Run: `python3 scripts/validate.py` — Expected: `OK  5 template file(s) pass static validation.`

- [ ] **Step 3: Live import** — Run: `python3 scripts/import_templates.py templates/mqtt/zigbee2mqtt_bridge_by_mqtt.yaml` — Expected: `OK`.

- [ ] **Step 4: Create `docs/zabbix-7.4-template-reference.md`** capturing verified facts

```markdown
# Zabbix 7.4 template export/import — verified reference

Facts confirmed against a live Zabbix 7.4.14 import for this repo. Keep in sync
when a new schema fact is learned from a real import failure.

## Structure
- `version: '7.4'` at the top of `zabbix_export`.
- Template groups: `template_groups:` at root. Shared `Templates/IoT` group UUID
  `9702754414644deba5cb4ed3e9f33594` — identical in every file (maps to the
  existing groupid 26 on the server).
- Triggers: ROOT level under `zabbix_export.triggers`, NOT inside the template.
- Value maps: INSIDE the template as `valuemaps:` (NOT root `value_maps:`).
- Linked base: child references it via a `templates:` block; import the base first.

## UUIDs
- Must be valid UUIDv4: 13th hex digit `4`, 17th in `8/9/a/b`. Generate with
  `python3 -c "import uuid;print(uuid.uuid4().hex)"`. Unique across all files
  except the shared group UUID.

## MQTT items (agent 2)
- Master: `type: ZABBIX_ACTIVE`, `key: mqtt.get[{$SESSION},{$TOPIC}]`,
  `value_type: TEXT`, `delay: '0'`. Broker/creds in the agent's named session
  (`Plugins.MQTT.Sessions.<name>.*`); {$TOPIC} is the FULL topic, passed verbatim.
- `mqtt.get` subscribes to ONE topic per item, so masters are per-topic.
- `nodata()` needs the master `history` > 0 (use `1h`).

## Preprocessing
- JSONPATH param is a single string, e.g. `$.linkquality`, array index `$.os.load_average[0]`.
- BOOL_TO_DECIMAL / DISCARD_UNCHANGED take an empty-string param.
- Water accumulation (SWV-ZF2): JS(emit "endtime|litres", throw to skip) ->
  DISCARD_UNCHANGED -> JS(parse litres). Confirmed working form: <fill in after Task 3 Step 4>.

## Import
- `configuration.import`, `format: yaml`. Rules: createMissing+updateExisting;
  items/triggers/templateDashboards deleteMissing:true (YAML authoritative);
  templateLinkage createMissing. Importer reports only the FIRST error then stops.
```

Fill the `<fill in after Task 3 Step 4>` with the actual working form observed.

- [ ] **Step 5: Full-suite re-import (idempotency check)**

Run: `python3 scripts/import_templates.py`
Expected: all 5 `OK`. Confirms dependency order and re-runnability.

- [ ] **Step 6: Commit**

```bash
git add templates/mqtt/zigbee2mqtt_bridge_by_mqtt.yaml docs/zabbix-7.4-template-reference.md
git commit -m "feat: z2m bridge template + Zabbix 7.4 reference doc"
```

---

## Task 7: README and final full validation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** — overview, template list, agent 2 MQTT session setup, per-host macro setup, import instructions. Use `.local` placeholder hostnames only.

```markdown
# zabbix-zigbee

Zabbix 7.4 templates for monitoring [zigbee2mqtt](https://www.zigbee2mqtt.io/)
devices over MQTT, via the Zabbix **agent 2** MQTT plugin. Recording + dashboards
— no device control.

## Templates

| Template | For |
|---|---|
| `Zigbee2MQTT common by MQTT` | base (linked by all device templates): linkquality, battery, firmware, liveness |
| `SONOFF SWV-ZF2 water valve by MQTT` | dual-channel smart water valve — per-event water litres, valve state, leak alert |
| `Tuya TS011F smart plug by MQTT` | metered smart plug (e.g. Nous A7Z) — state + power/current/voltage/energy |
| `Tuya TS0201 temp/humidity sensor by MQTT` | temperature + humidity sensor |
| `Zigbee2MQTT bridge by MQTT` | the z2m gateway itself — online, host/process health, per-device stats |

## How it works

z2m publishes each device's full state as JSON to `z2m/<device>`. Zabbix agent 2
subscribes via the MQTT plugin; one `mqtt.get` master item per device holds the
JSON and dependent items parse each metric with JSONPath. The bridge template
monitors the gateway from the retained `z2m/bridge/*` topics.

## Setup

### 1. Zabbix agent 2 MQTT session

On the Zabbix host, add a named MQTT session to `zabbix_agent2.conf` (or a
`.d` include):

    Plugins.MQTT.Sessions.zigbee.URL=tcp://mqtt.example.local:1883
    # If your broker needs auth:
    # Plugins.MQTT.Sessions.zigbee.User=<user>
    # Plugins.MQTT.Sessions.zigbee.Password=<password>

Restart agent 2. The session name (`zigbee`) is the `{$Z2M.SESSION}` macro default.

### 2. Import the templates

    cp scripts/.env.example scripts/.env   # fill in ZABBIX_URL + ZABBIX_TOKEN
    python3 scripts/import_templates.py

Imports the common base first, then device templates, then the bridge.

### 3. Create hosts

- One host per device, linked to its device template, with `{$Z2M.TOPIC}` set to
  the full topic (e.g. `z2m/garden-pump`). It inherits the common base.
- One host for the gateway, linked to `Zigbee2MQTT bridge by MQTT`
  (`{$Z2M.BRIDGE.TOPIC}` default `z2m/bridge`).

Set host Inventory mode to Automatic to auto-populate Model/Vendor.

## Notes

- Device topics are not retained: device items populate on the next change after
  the agent subscribes. Bridge topics are retained: they populate immediately.
- Water usage (SWV-ZF2) is recorded as clean per-completed-event litres; use
  `sum()` over 1d/7d/30d for daily/weekly/monthly totals.
```

- [ ] **Step 2: Final static validation** — Run: `python3 scripts/validate.py` — Expected: `OK  5 template file(s) pass static validation.`

- [ ] **Step 3: Final full import** — Run: `python3 scripts/import_templates.py` — Expected: all 5 `OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, template list, agent 2 MQTT session config"
```

---

## Post-implementation (manual, user-driven — out of scope for the agent)

- Functional test: configure the real agent 2 MQTT session, create hosts, confirm masters receive JSON and dependents populate; trigger a manual watering and confirm exactly one clean litres value per completed event.
- Rotate the Zabbix API token (it appeared in the build transcript; repo is public).
- Optional: dashboards (`dashboards/zigbee_fleet_overview.json`) and per-device LLD on `bridge/health.devices` — deferred enhancements from the spec.
