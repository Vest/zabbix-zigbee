# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A standalone, reusable **Zabbix 7.4 template set** for monitoring **zigbee2mqtt (z2m)** devices over **MQTT** via the **Zabbix agent 2 MQTT plugin**. Config + docs, published for reuse — not application code. Recording + dashboards only; no device automation/control.

**Status:** early. The only committed artifact so far is the approved design spec at `docs/superpowers/specs/2026-09-09-zabbix-zigbee-monitoring-design.md` — **read it first; it is the authoritative source for the architecture, the metric-by-metric mapping, and the hard rules below.** The templates, `scripts/import_templates.py`, README, etc. described there are not built yet. When implementing, follow the spec.

## Architecture (big picture)

```
zigbee2mqtt --publish--> MQTT broker --subscribe--> Zabbix agent 2 (MQTT plugin) --active checks--> Zabbix server
  z2m/<device>            (retained for bridge topics only)   runs ON the Zabbix host
```

- **One master `mqtt.get` item per device topic.** z2m publishes the *entire* device state as one JSON blob to `z2m/<device-name>` on every change, so each device gets exactly one `ZABBIX_ACTIVE` master (`mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]`, `value_type: TEXT`), and every scalar metric is a `DEPENDENT` item parsing that master's JSON via `JSONPATH` preprocessing.
- **Common base + linked device templates.** `Zigbee2MQTT common by MQTT` holds device-agnostic items (`linkquality`, `battery`, firmware-update-available, `nodata()` liveness). Device templates link it via a `templates:` block and add their own metrics. The bridge template is **standalone** (the gateway is not a Zigbee end device).
- **Retained vs not:** `z2m/bridge/{state,health,info}` are MQTT-retained → items populate immediately on subscribe. Device topics are **not** retained → they populate only on the next change. This is why cumulative counters (e.g. water litres) are derived by Zabbix from clean per-event values, not read from a device lifetime total.
- **Broker URL + credentials live in a Zabbix agent 2 named MQTT session** (`Plugins.MQTT.Sessions.<name>.*`), never in a template. `{$Z2M.TOPIC}` holds the FULL topic (`z2m/<device>`), passed verbatim — the session `Topic` field is a default only and is NOT prepended.
- **Active checks need `Hostname`.** `mqtt.get` items are active: agent 2 pulls its item list by matching its `Hostname` to a Zabbix host. One agent 2 serves all Zigbee hosts, so `zabbix_agent2.conf` `Hostname=` must list every Zigbee host name (comma-separated, appended to the existing value). Without it the items show no error but receive NO data — the agent never requests them.

## Hard rules (do not regress)

- **No hardcoded private data in committed files.** No real IP/MAC/device-name/broker/SSID as macro defaults or examples. Device-specific values are per-host input (macro `value` empty + `REQUIRED` in the description). Committed files (`.md`, `.yaml`, `README`, this file, `.env.example`) use **`.local` placeholder hostnames** (`mqtt.example.local`, `zabbix.example.local`) — never the real network. Real hostnames live only in the gitignored `scripts/.env` and in per-host Zabbix macros.
- **Shared template-group UUID** `9702754414644deba5cb4ed3e9f33594` (`Templates/IoT`) must be identical in every YAML file. It already exists on the target server (groupid 26).
- **`nodata()` needs history.** Any item a `nodata()` trigger reads must have `history` > 0. Masters otherwise use `history: '0'` (they are text blobs feeding dependents); metric items you want to graph (battery, LQI, temperature, humidity) keep `history` and `trends` > 0.
- **No `DISCARD_UNCHANGED_*` on metric items** (it breaks `nodata()` and `last()` staleness); acceptable only on constant inventory items (model/vendor).

## Zabbix 7.4 export/import schema gotchas

- **UUIDs must be valid UUIDv4** (13th hex digit `4`, 17th in `8/9/a/b`). Never hand-author — generate: `python3 -c "import uuid;print(uuid.uuid4().hex)"`. Unique across all files except the shared group UUID.
- **Triggers go at `zabbix_export` ROOT level**, not inside the template element. **Value maps go INSIDE the template** as `valuemaps:`, not root-level `value_maps:`.
- **Linked base** is referenced from a child via a `templates:` block; **import the base first** or the link is dropped. The importer reports only the FIRST error then stops — expect to iterate. No tabs; 2-space indent.
- Local validation ≠ import success — a live 7.4 import is the only true schema check.

## Commands

Target: **Zabbix 7.4** (verified server 7.4.14), agent 2 with the MQTT plugin.

```bash
# Live import (authoritative schema check). Config from gitignored scripts/.env
# (ZABBIX_URL, ZABBIX_TOKEN). Imports common base(s) before linked device templates.
python3 scripts/import_templates.py                 # all templates, in dependency order
python3 scripts/import_templates.py FILE [FILE...]   # only the given files, in order
python3 scripts/import_templates.py --dry-run        # list what would import, no network
python3 scripts/import_templates.py --insecure       # skip TLS verification (self-signed https)
```

The import script is stdlib-only (no pip). It uses `createMissing + updateExisting`; items/triggers/template-dashboards use `deleteMissing: true` so the **YAML is authoritative** — removing an item from a template file and re-importing deletes it on the server. Manage these templates via the repo, not the Zabbix UI (UI-added objects on these templates are deleted on the next import).

## Conventions

- Do not commit unless explicitly asked.
- Template names use the **Zigbee model ID + a short function descriptor** (e.g. `Tuya TS011F smart plug by MQTT`); the fuller detail (vendor, manufacturer code, matching friendly-names, exposes) goes in the template description. The one exception is a genuinely branded model (`SONOFF SWV-ZF2 water valve by MQTT`).
- Keep `docs/zabbix-7.4-template-reference.md` in sync when a new schema fact is learned from a real import.
