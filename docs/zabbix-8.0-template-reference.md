# Zabbix 8.0 template export/import — verified reference

Facts confirmed against a live Zabbix 8.0.0 import for this repo. Keep in sync
when a new schema fact is learned from a real import failure. (Originally
verified on 7.4.14; the set was migrated to 8.0 — notably native JSON masters.)

## Structure
- `version: '8.0'` at the top of `zabbix_export`.
- Template groups: `template_groups:` at root. Shared `Templates/IoT` group UUID
  `9702754414644deba5cb4ed3e9f33594` — identical in every file (maps to the
  existing groupid 26 on the server).
- Triggers: ROOT level under `zabbix_export.triggers`, NOT inside the template.
- Value maps: INSIDE the template as `valuemaps:` (NOT root `value_maps:`).
- Linked base: child references it via a `templates:` block; import the base first.

## Naming (learned from a real import failure)
- A template `name`/`template` (technical name) MUST NOT contain `/`. The import
  rejects it with `Invalid parameter "/1/host": invalid host name`. Use `-` or a
  word instead (e.g. `temp-humidity`, not `temp/humidity`).

## Value maps are NOT inherited via linkage (learned from a real import failure)
- If a device template links a base and its ITEMS reference a value map, that
  value map must be defined IN THE DEVICE TEMPLATE'S OWN `valuemaps:` block —
  linkage does not import the base's value maps for the child's items. Symptom:
  `Cannot find value map "<name>" used for item "<item>" on "<template>"`.
- Consequence for this repo: `Zigbee boolean` / `Zigbee state` are duplicated
  into every template whose items use them (base, valve, plug, bridge). The
  importer allows the same value-map NAME across templates; only UUIDs must be
  unique per file (and are). `valueMaps` import rule uses `deleteMissing:false`.

## UUIDs
- Must be valid UUIDv4: 13th hex digit `4`, 17th in `8/9/a/b`. Generate with
  `python3 -c "import uuid;print(uuid.uuid4().hex)"`. Unique across all files
  except the shared group UUID. `scripts/validate.py` enforces this.

## MQTT items (agent 2)
- Master: `type: ZABBIX_ACTIVE`, `key: mqtt.get[{$SESSION},{$TOPIC}]`,
  `value_type: JSON`, `history: '0'`, `delay: '0'`. Broker/creds in the agent's
  named session (`Plugins.MQTT.Sessions.<name>.*`); `{$TOPIC}` is the FULL topic,
  passed verbatim (the session Topic field is a default only, not prepended).
- `mqtt.get` subscribes to ONE topic per item, so masters are per-topic. The
  bridge template therefore has three masters (state, health, info).
- **Native JSON value type (8.0, ZBXNEXT-10069).** Masters are `value_type: JSON`
  so the UI renders them as structured JSON and the payload is typed correctly.
  JSONPath dependents parse a JSON master exactly as they did a TEXT master
  (`$.property`) — verified live: all device/bridge dependents extract values with
  the master typed JSON. Masters stay `history: '0'` so the raw blob is never
  stored (only the parsed dependents are) — JSON storage/history is deliberately
  NOT used here (the device blobs would cost storage; the bridge/info blob is huge).

## nodata() cannot read a JSON or binary item (learned from a live import failure)
- `nodata()` supported value types: **Integer, Float, Character, Text, Log**
  (per [8.0 docs](https://www.zabbix.com/documentation/8.0/en/manual/config/triggers/expression/history#nodata)).
  JSON and Binary are NOT supported. A JSON master + `nodata()` trigger is rejected
  at import: `Incorrect item value type "JSON" provided for trigger function
  "nodata"`.
- Consequence: liveness never runs on the JSON master. It runs on a stored,
  non-JSON dependent instead:
  - **Devices:** `nodata(/.../z2m.linkquality,{$Z2M.DATA.TIMEOUT})` — `linkquality`
    (UNSIGNED) is present in every z2m device payload and kept with history.
  - **Bridge:** a dedicated `z2m.bridge.heartbeat` (UNSIGNED) dependent parsing
    `$.response_time` from each bridge/health publish; `nodata()` reads it.
- Any `nodata()` target must be non-JSON AND have `history` > 0.
- `sec` (the window) must be ≥ 30s — the history syncer evaluates `nodata()` only
  every 30s, and `nodata(/host/key,0)` is disallowed. This repo's macros
  (`{$Z2M.DATA.TIMEOUT}=2h` base, `{$Z2M.BRIDGE.DATA.TIMEOUT}=30m`) are well above that.
- **Tune `{$Z2M.DATA.TIMEOUT}` per device class — reporting cadence varies wildly.**
  z2m devices publish on change, so a `nodata()` window must exceed the device's
  real idle interval or it false-flaps. Verified live: an idle TS011F mains plug
  (relay off, ~0 W) can go 5+ hours between messages, so the TS011F template
  overrides the macro to `24h` (nearest-template value wins over the base `2h`).
  Battery valves/sensors report more regularly but still infrequently — keep the
  window generous (hours). The alert firing on a quiet-but-healthy device is
  "correct but unwanted": it auto-resolves the moment data returns.

## Preprocessing (verified type codes from the live server)
- JSONPATH (type 12) param is a single string: `$.linkquality`, array index
  `$.os.load_average[0]`, nested `$.process.uptime_sec`.
- JAVASCRIPT is type 21; DISCARD_UNCHANGED is type 19; DISCARD_UNCHANGED_HEARTBEAT
  and BOOL_TO_DECIMAL take an (empty or duration) string param.
- **Water accumulation (SWV-ZF2) — VERIFIED WORKING FORM.** A dependent item can
  carry a 3-step chain that emits litres only once per completed irrigation event:
  1. JAVASCRIPT: parse the master JSON; if `schedule_status !== "end"`, `throw`
     (throwing skips storing this value); else return `actual_end_time + "|" + actual_irrigation_amount`.
  2. DISCARD_UNCHANGED (no param): drops a republished identical completed event.
  3. JAVASCRIPT: `return parseFloat(value.split("|")[1]);` — the clean litres number.
  Confirmed accepted and stored in order on Zabbix 7.4.14 and re-verified on 8.0
  (item `z2m.valve.event_litres[1]`). Zabbix `sum()` over this gives litres/day etc.
  Note: `throw` in step 1 is how you conditionally skip storing a value — there is
  no cross-invocation JS state, so DISCARD_UNCHANGED (not JS memory) does the dedup.

## Import
- `configuration.import`, `format: yaml`. Rules: createMissing+updateExisting;
  items/triggers/templateDashboards `deleteMissing:true` (YAML authoritative);
  `templateLinkage` createMissing; `valueMaps` deleteMissing:false. The importer
  reports only the FIRST error then stops — expect to iterate. Re-import is
  idempotent (all 6 templates re-import OK in dependency order).

## Capability mix-in templates + the "linked twice" trap (learned live)
- Battery is a device *capability*, not universal: mains Routers (smart plugs)
  publish no `$.battery`, so a bare `JSONPATH: $.battery` makes the item "Not
  supported" on them. Rather than suppress it, battery lives in its own mix-in
  template `Zigbee2MQTT battery device by MQTT` (links the common base so the
  master item is in scope), linked ONLY by battery devices (valve, sensor). Mains
  plugs link the common base directly and have no battery item at all.
- **A template may not inherit the same parent via two paths.** If a device links
  the common base directly AND links the battery mix-in (which also links common),
  the import fails: `parent template "Zigbee2MQTT common by MQTT" would be linked
  twice`. Fix: battery devices link ONLY the mix-in and inherit common
  transitively through it.
- **Migration gotcha:** the importer cannot swap a template's existing DIRECT link
  to a parent for a TRANSITIVE one in a single import — the pre-existing direct
  link still trips the "linked twice" check. When restructuring linkage on
  templates already on the server, first clear the stale direct link via
  `template.update` with `templates_clear`, then re-import. (A fresh import onto a
  clean server does not hit this.)
- **⚠ Relinking templated items on a POPULATED host DESTROYS their history.**
  Zabbix history and trends are keyed by `itemid`. Detaching + reattaching a
  template (which is what `templates_clear` + relink does) recreates the host's
  templated items with NEW itemids, so all prior history/trends for those items
  are orphaned and purged — unrecoverable from Zabbix (no DB backup = gone).
  Learned the hard way: the battery mix-in migration relinked the sensor and valve
  templates, wiping ~61 days of battery/LQI/temperature/humidity history on
  `base-out` and `garden-pump`. The plugs, never relinked, kept their history.
  Lesson: before changing linkage on templates already attached to populated
  hosts, decide whether the historical data matters — if it does, snapshot the DB
  first, or avoid the relink. This is a Zabbix behaviour, not specific to this repo.
- **Corollary: new itemids break dashboard item-value widgets pinned to them.**
  Standalone item (single-value) widgets reference an item by `itemid.0` (field
  type 4). After a relink gives items new itemids, those widgets show *"No
  permissions to referred object or it does not exist!"* Fix: re-run
  `scripts/create_dashboard.py` — it re-resolves its named placeholders
  (`GARDEN_WATER_TOTAL`, etc.) to the current live itemids. svggraph widgets that
  reference items by NAME PATTERN (`ds.N.items.N`) are unaffected (they match on
  name, not itemid) — which is why after a relink the pattern graphs survive but
  the pinned single-value tiles break.

## Standalone dashboards (dashboards/ + dashboard.create)
- Standalone (non-template) dashboards are NOT part of `configuration.export`;
  deploy via the `dashboard.create`/`dashboard.update` API from a portable JSON.
- Widget field type codes: 0=integer, 1=string, 2=host group, 3=host, 4=item.
- **svggraph draw type `ds.N.type`: `0`=Line (default), `1`=Points, `2`=Staircase,
  `3`=Bar.** (Easy to get backwards — setting `1` renders dots, not a line.)
- Item value widget needs `show.N` fields to control content: 1=description,
  2=value, 3=time, 5=change indicator. Without them it shows the time large and
  the name as the value. `value_size`/`decimal_size` size the number.
- tophosts: `columns.N.data` codes: `1`=Item value (REQUIRES `columns.N.item`),
  `2`=Host name, `3`=Text. Minimum working column set (verified live): a Host-name
  column is just `{data:2, name}`; an Item-value column is `{data:1, name, item,
  base_color}`. Two things that make it "not fully configured" even though the API
  accepts the create: (1) a **present-but-EMPTY `base_color`** (`""`) fails
  validation — omit the field entirely instead of sending blank; (2) `display=1`
  ("As is") combined with `min`/`max` is invalid — min/max only apply to the bar/
  indicator displays. Set `base_color` (a real hex) to get the green bar; drop
  display/min/max. `column` = the 1-based sort column index.
- Template names (technical `name`) must NOT contain `/` — rejected as an invalid
  host name.
