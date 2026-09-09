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
  `value_type: TEXT`, `delay: '0'`. Broker/creds in the agent's named session
  (`Plugins.MQTT.Sessions.<name>.*`); `{$TOPIC}` is the FULL topic, passed
  verbatim (the session Topic field is a default only, not prepended).
- `mqtt.get` subscribes to ONE topic per item, so masters are per-topic. The
  bridge template therefore has three masters (state, health, info).
- `nodata()` needs the master `history` > 0 (this repo uses `1h`).

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
  Confirmed accepted and stored in order on Zabbix 7.4.14 (item
  `z2m.valve.event_litres[1]`). Zabbix `sum()` over this gives litres/day etc.
  Note: `throw` in step 1 is how you conditionally skip storing a value — there is
  no cross-invocation JS state, so DISCARD_UNCHANGED (not JS memory) does the dedup.

## Import
- `configuration.import`, `format: yaml`. Rules: createMissing+updateExisting;
  items/triggers/templateDashboards `deleteMissing:true` (YAML authoritative);
  `templateLinkage` createMissing; `valueMaps` deleteMissing:false. The importer
  reports only the FIRST error then stops — expect to iterate. Re-import is
  idempotent (all 5 templates re-import OK in dependency order).
