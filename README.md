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
| `Tuya TS0201 temp-humidity sensor by MQTT` | temperature + humidity sensor |
| `Zigbee2MQTT bridge by MQTT` | the z2m gateway itself — online, host/process health, per-device stats |

## How it works

z2m publishes each device's full state as JSON to `z2m/<device>`. Zabbix agent 2
subscribes via the MQTT plugin; one `mqtt.get` master item per device holds the
JSON and dependent items parse each metric with JSONPath. The bridge template
monitors the gateway from the retained `z2m/bridge/*` topics.

## Setup

### 1. Zabbix agent 2 MQTT session

On the Zabbix host, add a named MQTT session to `zabbix_agent2.conf` (or a
`.d/` include):

    Plugins.MQTT.Sessions.zigbee.URL=tcp://mqtt.example.local:1883
    # If your broker needs auth:
    # Plugins.MQTT.Sessions.zigbee.User=<user>
    # Plugins.MQTT.Sessions.zigbee.Password=<password>

Restart agent 2. The session name (`zigbee`) is the `{$Z2M.SESSION}` macro default.

### 2. Import the templates

    cp scripts/.env.example scripts/.env   # fill in ZABBIX_URL + ZABBIX_TOKEN
    python3 scripts/import_templates.py

Imports the common base first, then device templates, then the bridge. Re-runnable
(the YAML is authoritative — items/triggers removed from a file are deleted on
re-import; manage these templates via the repo, not the UI).

`python3 scripts/validate.py` runs offline static checks (UUIDv4, no tabs,
value-map/trigger placement, no cross-file duplicate UUIDs) before you import.

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

## License

MIT — see [LICENSE](LICENSE).
