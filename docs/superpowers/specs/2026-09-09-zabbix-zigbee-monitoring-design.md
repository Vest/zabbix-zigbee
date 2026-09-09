# Zabbix monitoring for Zigbee (zigbee2mqtt) devices — design

Date: 2026-09-09
Status: approved (pending written-spec review)

## Goal

Record home-automation metrics and statistics for Zigbee devices exposed by
**zigbee2mqtt** (z2m), monitored in **Zabbix 7.4** via the **agent 2 MQTT
plugin**. Recording + dashboards only — no automation/control. The showcase
device is the **SONOFF SWV-ZF2** dual-channel smart water valve ("garden-pump"):
we want real water-usage statistics (litres per event / per day / per month),
battery, link quality, and fault alerting.

This is a standalone, reusable **Zabbix 7.4 template set** for zigbee2mqtt
devices, published for reuse — config + docs, not application code. The design
uses the MQTT master/dependent pattern described below throughout.

## Scope (first pass)

Build **five templates** covering the visible fleet plus the gateway:

1. `Zigbee2MQTT common by MQTT` — base; device-agnostic metrics every z2m device
   publishes (`linkquality`, `battery`) + liveness. Every device template links it.
2. `SONOFF SWV-ZF2 water valve by MQTT` — the garden-pump; the detailed showcase.
3. `Tuya TS011F smart plug by MQTT` — base-plug-1, base-plug-2, living-plug.
   Nous A7Z / Tuya TS011F (`manufacturer _TZ3008_reatplte`, vendor Nous). Power metering.
4. `Tuya TS0201 temp/humidity sensor by MQTT` — base-out. Tuya TH09Z / TS0201
   (`_TZ3000_yupc0pb7`).
5. `Zigbee2MQTT bridge by MQTT` — the z2m gateway itself, monitored as its own
   Zabbix host (state, host health, per-device stats, inventory). Standalone
   (does NOT link the common base — the bridge is not a Zigbee end device).

**Naming: by Zigbee model ID + a short 1–2 word function descriptor** (e.g.
"Tuya TS011F smart plug"). The template NAME carries model ID + function words so
the list view is instantly recognizable; the DESCRIPTION carries fuller detail
(vendor, manufacturer code, matching friendly-names, exposes summary). Precise
and reusable for a public repo; the same template serves any device reporting
that model ID.

Plus repo scaffolding: `scripts/import_templates.py`, `.gitignore`,
`.env.example`, `LICENSE`, `README.md`, `CLAUDE.md`, and a
`docs/zabbix-7.4-template-reference.md` (kept in sync as schema facts are learned).

## Architecture & data flow

```
zigbee2mqtt ──publish──> mqtt.example.local:1883 ──subscribe──> Zabbix agent 2 (MQTT plugin)
  z2m/<device>            (topic z2m/<device>)                running ON the Zabbix host
                                                                     │ active checks
                                                                     ▼
                                                        Zabbix server: master + dependent
                                                        items → triggers → dashboards
```

Key facts (verified against the live garden-pump payload and z2m behaviour):

- **One JSON blob per device.** z2m publishes the *entire* device state as a
  single JSON object to `z2m/<device-name>` on every change. So each device has
  **exactly one master `mqtt.get` item**, and every metric is a **DEPENDENT** item
  parsing that master's JSON via JSONPATH.
- **Messages are NOT retained (device topics).** For `z2m/<device>` topics the
  MQTT plugin only sees messages published after it subscribes. Acceptable: we
  want ongoing recording, not backfill. A consequence: cumulative counters must
  be derived by Zabbix, not read from a device lifetime total.
- **Bridge topics ARE retained.** `z2m/bridge/state`, `z2m/bridge/info`,
  `z2m/bridge/health` are published with the MQTT retain flag, so the broker
  delivers their last value to Zabbix immediately on (re)subscribe — bridge items
  populate instantly, unlike device items which wait for the next change. This
  asymmetry is documented in the relevant template descriptions.
- **No per-device LWT online topic** here (garden-pump shows "Availability:
  Disabled"). Liveness = `nodata()` on the master item. The z2m gateway's own health is monitored by the dedicated
  bridge template (`z2m/bridge/*`), see below.
- Broker URL + credentials live in a Zabbix **agent 2 named MQTT session**
  (`Plugins.MQTT.Sessions.<name>.*`), NOT in any template. Items reference it:
  `mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]`.

## User priorities (must-haves, stated)

- **Battery tracking with alerting** — battery items + low-battery triggers
  (base). Battery devices: garden-pump, base-out.
- **Link quality as a statistic** — LQI items kept with generous history/trends
  for long-term graphs; weak-link trigger present but tuned to be informative,
  not noisy (statistic-first).
- **Temperature and humidity** — first-class items on the sensor template, with
  history for trending.

These drive retention choices: battery/LQI/temperature/humidity items keep
`history` and `trends` > 0 (they are the statistics you want), unlike the raw
master blobs (`history: 0`).

## Template design (do not regress)

- **Master/dependent.** One `ZABBIX_ACTIVE` master `mqtt.get` per device topic
  (`value_type: TEXT`, `history: '0'` unless a `nodata()` trigger reads it, in
  which case `history: '1h'`). All scalars are `DEPENDENT` with `JSONPATH`.
- **No hardcoded private data.** No IP/MAC/device-name/broker/SSID as macro
  defaults or examples. Device-specific values are per-host input: macro `value`
  empty + `REQUIRED` noted in the description. Templates stay generic/shareable.
  **Committed files (`.md`, `.yaml`, `README`, `CLAUDE.md`, `.env.example`) use
  placeholder hostnames under `.local`** (e.g. `mqtt.example.local`,
  `zabbix.example.local`) — never a real internal domain. Real hostnames
  live only in the gitignored `scripts/.env` and in per-host Zabbix macros.
- **Macros** (base): `{$Z2M.SESSION}` (agent MQTT session name, default `zigbee`),
  `{$Z2M.TOPIC}` (FULL topic, e.g. `z2m/<device-name>` — REQUIRED, empty default,
  passed verbatim; session `Topic` field is a default only, not prepended),
  `{$Z2M.DATA.TIMEOUT}` (for `nodata()`), `{$Z2M.BATTERY.MIN}` (low-battery %),
  `{$Z2M.LINKQUALITY.MIN}` (weak-link LQI). Device templates add their own
  (e.g. `{$Z2M.POWER.MAX}` on the plug).
- **Common-base shared items** (every z2m device publishes these — confirmed
  across garden-pump, plugs, sensor): `linkquality` (LQI), `battery` (%; empty on
  mains devices, fine), and a **firmware "update available"** item derived from
  `$.update` — 1 when `update.state == "available"` OR
  `update.installed_version != update.latest_version`, else 0 (JS step).
  `update.state` values seen live: idle/scheduled/available/updating.
- **Booleans / enums → value maps.** z2m string enums (`state_1` "ON"/"OFF",
  `child_lock` "LOCK"/"UNLOCK", `valve_abnormal_state` "normal"/…) are mapped to
  UNSIGNED via a JS/replace step + value map for clean graphs and triggers.
- **`nodata()` needs history.** Any item a `nodata()` trigger reads must have
  `history` > 0 — the master carries `history: '1h'` for this reason.
- **No `DISCARD_UNCHANGED_*`** on metric items (breaks `nodata()`/`last()`
  staleness); OK on constant inventory items (model/vendor).
- **Shared group UUID** `9702754414644deba5cb4ed3e9f33594` (`Templates/IoT`) —
  identical in every file.

## Garden-pump (SWV-ZF2) metrics

Source: live `z2m/garden-pump` payload. Master item key
`mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]`.

| Metric | Type | JSONPath / logic | Notes |
|---|---|---|---|
| Battery | UNSIGNED % | `$.battery` | low-battery trigger |
| Link quality (LQI) | UNSIGNED | `$.linkquality` | weak-link trigger |
| Valve state ch1 | UNSIGNED (map) | `$.state_1` → ON=1/OFF=0 | |
| Valve state ch2 | UNSIGNED (map) | `$.state_2` → ON=1/OFF=0 | |
| Live run duration ch1 | UNSIGNED min | `$.real_time_irrigation_duration_1` | |
| Live run duration ch2 | UNSIGNED min | `$.real_time_irrigation_duration_2` | |
| Live volume this run | FLOAT L | `$.real_time_irrigation_volume` | |
| Volume this hour | FLOAT L | `$.hour_irrigation_volume` | |
| **Water used, event ch1** | FLOAT L | see accumulation logic below, ch1 | per completed event |
| **Water used, event ch2** | FLOAT L | see accumulation logic below, ch2 | per completed event |
| **Water used, event total** | FLOAT L | JS sum of ch1+ch2 event litres | the "summed" metric |
| Valve abnormal state | UNSIGNED (map) | `$.valve_abnormal_state` → normal=0/other=1 | **fault/leak trigger** |
| Child lock | UNSIGNED (map) | `$.child_lock` → UNLOCK=0/LOCK=1 | |
| Firmware update state | CHAR | `$.update.state` | idle/available/updating |
| Model (inventory) | CHAR | constant `SWV-ZF2` | `inventory_link: MODEL`, discard-unchanged |
| Vendor (inventory) | CHAR | constant `SONOFF` | `inventory_link: VENDOR`, discard-unchanged |

### Water-usage accumulation (the important subtlety)

`irrigation_schedule_status_N.actual_irrigation_amount` reports litres for the
*most recent* event (e.g. 13, then 0), and the whole payload is re-published on
every unrelated change. Storing it raw would double-count on republish and
inject spurious zeros into time-based sums.

**Solution — JAVASCRIPT preprocessing on each per-channel "Water used, event"
item.** Emit the litres value **only when a newly-completed event is detected**,
otherwise return a not-supported/discard sentinel so nothing is stored:

- read `irrigation_schedule_status_N`
- proceed only if `schedule_status === "end"`
- compare `actual_end_time` against the last one seen (persisted via item
  history / a Zabbix JS `value`+`prev` comparison; if prev-in-preprocessing is
  unavailable, use `DISCARD_UNCHANGED` keyed on a synthesized
  `actual_end_time|actual_irrigation_amount` string emitted by the JS, so an
  unchanged event is discarded and only a new completed event stores its litres)
- emit `actual_irrigation_amount` (litres) for that new event

The "event total" item sums the two channels' newly-completed litres with the
same guard. **Verify the exact prev-value mechanism against Zabbix 7.4 during
implementation** — this is the one piece to validate live.

Zabbix then derives statistics from these clean per-event values:
- **Litres today**: `sum()` of the event item over `1d` (dashboard / calculated item)
- **Litres this week / month**: `sum()` over `7d` / `30d`
These are dashboard aggregations / optional calculated items, not new device data.

### Garden-pump triggers

- Battery low: `last(battery) < {$Z2M.BATTERY.MIN}` — WARNING.
- Weak link: `max(linkquality,15m) < {$Z2M.LINKQUALITY.MIN}` — WARNING.
- **Valve abnormal**: `last(valve_abnormal_state)=1` — HIGH (leak/shortage/fault).
- No data: `nodata(master,{$Z2M.DATA.TIMEOUT})=1` — WARNING (device silent).

## Plug template — `Tuya TS011F smart plug by MQTT`

For base-plug-1, base-plug-2, living-plug. **Confirmed live**: Nous A7Z / Tuya
TS011F, vendor Nous, `manufacturer _TZ3008_reatplte`. Master
`mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]`, links the base. Fields (all verified
from real payloads / exposes):

| Metric | Type | JSONPath | Notes |
|---|---|---|---|
| State | UNSIGNED (map) | `$.state` → ON=1/OFF=0 | on/off |
| Power | FLOAT W | `$.power` | high-power trigger `{$Z2M.POWER.MAX}` |
| Current | FLOAT A | `$.current` | |
| Voltage | FLOAT V | `$.voltage` | over/under-voltage optional |
| Energy | FLOAT kWh | `$.energy` | cumulative device counter (monotonic) |
| Child lock | UNSIGNED (map) | `$.child_lock` → UNLOCK=0/LOCK=1 | |
| Link quality | UNSIGNED | `$.linkquality` | (from base, if not overridden) |
| Firmware update state | CHAR | `$.update.state` | idle/scheduled/available/updating |

`energy` is a cumulative kWh counter, so daily/weekly consumption is a Zabbix
`change()`/`delta` over the counter (dashboard/calculated), not new device data.
Triggers: high power, no data. Battery/linkquality inherited from base (plugs are
mains-powered Routers — no battery; the base battery item simply stays empty,
which is fine, and the low-battery trigger won't fire).

## Temperature/humidity sensor template — `Tuya TS0201 temp/humidity sensor by MQTT`

For base-out. **Confirmed live**: Tuya TH09Z / TS0201, `_TZ3000_yupc0pb7`. Master
`mqtt.get[{$Z2M.SESSION},{$Z2M.TOPIC}]`, links the base.

| Metric | Type | JSONPath | Notes |
|---|---|---|---|
| Temperature | FLOAT °C | `$.temperature` | optional high/low triggers (macros) |
| Humidity | FLOAT % | `$.humidity` | |
| Battery | UNSIGNED % | `$.battery` | (from base) low-battery trigger |
| Battery voltage | FLOAT mV | `$.voltage` | diagnostic; in exposes but NOT always published — best-effort |
| Link quality | UNSIGNED | `$.linkquality` | (from base) |

Triggers: battery low (inherited), optional high/low temperature (macro-bounded),
no data.

## Bridge template (z2m gateway) — `Zigbee2MQTT bridge by MQTT`

Monitors the zigbee2mqtt gateway itself, as its own Zabbix host — the "master
host" of the Zigbee fleet (analogous to monitoring the Zabbix server or a
hypervisor). **Standalone template** (does not link the common base; the bridge
is not a Zigbee end device, has no battery/linkquality).

**Three master `mqtt.get` items** (separate retained topics):
`mqtt.get[{$Z2M.SESSION},{$Z2M.BRIDGE.TOPIC}/state]`, `.../health`, `.../info`.
`{$Z2M.BRIDGE.TOPIC}` default `z2m/bridge`. Retained → items populate immediately
on subscribe. `health` publishes every `{health.interval}` minutes (confirmed
config: **10 min**).

Confirmed `bridge/health` structure (live):
`{response_time, os:{load_average:[1m,5m,15m], memory_used_mb, memory_percent},
process:{uptime_sec, memory_used_mb, memory_percent},
mqtt:{connected, queued, published, received},
devices:{<ieee>:{messages, messages_per_sec, leave_count, network_address_changes}}}`

| Metric | Topic | JSONPath / logic | Trigger |
|---|---|---|---|
| **Bridge online** | `state` | `$.state` → online=1/other=0 (map) | **HIGH: gateway offline** |
| Host load average (1m) | `health` | `$.os.load_average[0]` | optional high-load (macro) |
| Host memory percent | `health` | `$.os.memory_percent` | WARNING: `{$Z2M.BRIDGE.MEM.MAX}` |
| z2m process uptime | `health` | `$.process.uptime_sec` (units s) | INFO: restarted (uptime drop) |
| z2m process memory | `health` | `$.process.memory_used_mb` (MB) | leak watch |
| MQTT connected | `health` | `$.mqtt.connected` → 1/0 (map) | WARNING: broker link down |
| MQTT queued | `health` | `$.mqtt.queued` | WARNING: backlog >0 sustained |
| MQTT published (total) | `health` | `$.mqtt.published` | throughput (counter) |
| **Total device leaves** | `health` | JS: sum of `devices.*.leave_count` | **WARNING: a device left the network** |
| Total msgs/sec (all devices) | `health` | JS: sum of `devices.*.messages_per_sec` | network chattiness / storm detection |
| Device count | `health` | JS: count of `devices` keys | WARNING: dropped below baseline |
| Zigbee channel | `info` | `$.config.advanced.channel` | inventory (static, =11) |
| z2m version | `info` | `$.version` | inventory / version tracking |
| Pan ID | `info` | `$.config.advanced.pan_id` | inventory |
| Coordinator type | `info` (from devices) | via `bridge/devices` Coordinator entry | inventory |

Per-device `leave_count` / `messages_per_sec` are also excellent candidates for
**LLD (low-level discovery)** — one bridge master could discover every device from
`health.devices` and auto-create per-device stat items. Deferred as a possible
enhancement; the initial pass uses JS-aggregated totals (simpler, no LLD).

Macros: `{$Z2M.SESSION}` (shared with devices), `{$Z2M.BRIDGE.TOPIC}` (default
`z2m/bridge`), `{$Z2M.BRIDGE.MEM.MAX}` (host memory % warn, default 90),
`{$Z2M.BRIDGE.DATA.TIMEOUT}` (generous nodata window for `health`, ≥ 2×10 min).

**The bridge-offline trigger is the highest-value alert in the project**: if the
gateway dies every device silently goes stale, so this single check means "your
Zigbee is down" instead of N separate no-data alerts. `bridge/state` history > 0
so the trigger can read it. Log-error counting from `z2m/bridge/logging` is
intentionally OUT of scope (high-volume noise at home scale).

## Dashboard

A template-level dashboard on the garden-pump, plus a
repo `dashboards/zigbee_fleet_overview.json` host-dashboard for the whole fleet:

- Garden-pump page: water-used-today (single value, `sum 1d`), water-used-30d,
  litres/day bar graph (svggraph), valve state timeline, battery + LQI gauges,
  abnormal-state indicator.
- Fleet page: battery levels across all battery devices, link-quality across all
  devices, plug power draw, base-out temperature/humidity, z2m bridge online.

## Repo layout

```
templates/mqtt/   the five templates above
docs/             zabbix-7.4-template-reference.md, superpowers/specs/
scripts/          import_templates.py (adapted DEFAULT_FILES + docstring), .env.example
dashboards/       zigbee_fleet_overview.json, README.md
README.md  CLAUDE.md  LICENSE  .gitignore
```

Import order: **common base first**, then the three linked device templates
(they reference the base by name via a `templates:` block); the **bridge template
is standalone** (any order). `import_templates.py` uses
`createMissing+updateExisting`, `templateLinkage` create, and `deleteMissing:true`
on items/triggers/dashboards so the YAML is authoritative.

## Zabbix 7.4 schema gotchas (inherited — see reference doc)

- UUIDs must be valid UUIDv4 (13th hex `4`, 17th in `8/9/a/b`) — generate, never
  hand-author; unique across files except the shared group UUID.
- Triggers at `zabbix_export` ROOT level; value maps INSIDE the template.
- Linked base referenced via `templates:` block; import base first.
- Importer reports only the first error then stops — expect to iterate. No tabs;
  2-space indent. Local validation ≠ import success; a live 7.4 import is the
  only true check.

## Testing / validation

1. Static: a validation snippet (UUIDv4, no tabs, no
   root-level value_maps, no in-template triggers, no unexpected dup UUIDs).
2. Live: `python3 scripts/import_templates.py` against the real Zabbix 7.4.
3. Functional: create a host, set `{$Z2M.SESSION}`/`{$Z2M.TOPIC}`, configure the
   agent 2 MQTT session for `mqtt.example.local:1883`, confirm the master receives
   JSON and dependents populate. Trigger a manual watering to confirm a single
   clean litres value is recorded per completed event (the accumulation guard).

## Open item to verify during implementation

- The exact per-event dedup mechanism for water accumulation on Zabbix 7.4
  (prev-value-in-JS vs `DISCARD_UNCHANGED` on a synthesized key). Design commits
  to "one clean value per completed event"; the mechanism is validated live.

Device JSON field names for ALL five templates are confirmed from live payloads
(garden-pump, living-plug, base-out, bridge/state, bridge/health, bridge/info) —
no longer open.

