# Dashboards

Global (fleet) dashboards for the Zigbee hosts. Unlike templates, Zabbix global
dashboards are **not** part of `configuration.export`, so these are stored as
portable JSON (server-specific ids stripped) suitable for the `dashboard.create`
API method.

## zigbee_fleet_overview.json

One screen for all Zigbee devices (filtered by the `Zigbee` host group), using
item-name **patterns** and host wildcards so new devices are picked up
automatically:

- **Zigbee problems** — live problems for the `Zigbee` group (low battery, valve
  abnormal, weak link, no data, bridge offline…).
- **Battery levels (lowest first)** — hosts ranked by `Battery`, bar display.
- **Water used today / Live irrigation volume** — garden-pump single values
  (water today = `sum` over 1d of per-event litres).
- **Bridge online / Devices online / Host memory** — gateway health tiles.
- **Water used per completed event (30d)** — the irrigation trend.
- **Battery — all devices (7d)** — `Battery` per device, 0–100 axis.
- **Link quality / LQI — all devices (7d)** — `Link quality (LQI)` per device.
- **Temperature (7d)** / **Humidity (7d)** — climate from the sensor(s).
- **Plug power (7d)** — `Power` across `*plug*` hosts.

### Deploy it

Requires the `Zigbee` host group and the Zigbee hosts (linked to the templates,
`{$Z2M.TOPIC}` set) to exist. A few single-value widgets need concrete itemids;
the JSON uses named placeholders (`GARDEN_WATER_TOTAL`, `BRIDGE_ONLINE`, …) that
`scripts/create_dashboard.py` resolves against the live server before calling
`dashboard.create` (or `dashboard.update` if it already exists):

    python3 scripts/create_dashboard.py

The group filter and item patterns are portable; widget field formats are Zabbix
7.4-specific.
