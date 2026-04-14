# PI3_MQTT_Monitor — Design

## 1. Purpose
Run one MQTT client process on the Raspberry Pi 3 that owns MQTT subscriptions and dispatches actions for multiple features.

Initial merged features:
- Sense HAT MQTT control/status
- SmartCam stream start/stop control

Future features can be added by extending config and handlers rather than creating new services.

## 2. Core design
A single long-running Python process:
- connects to MQTT broker
- loads a config file describing topics and actions
- dispatches commands to feature handlers
- publishes status/results back to MQTT

## 3. Why one service is better
Compared with multiple independent services, one MQTT monitor gives:
- one broker connection
- one service to start at boot
- one place for topic routing
- easier logs and recovery
- easier future expansion

## 4. Proposed file layout
```text
projects/PI3_MQTT_Monitor/
  README.md
  DESIGN.md
  config.json
  pi3_mqtt_monitor.py
  handlers/
    __init__.py
    smartcam.py
    sensehat.py
```

## 5. Config-driven routing
Example config structure:
```json
{
  "mqtt": {
    "host": "MQTT_BROKER_IP_OR_HOSTNAME",
    "port": 1884
  },
  "topics": {
    "smartcam/pi3/control": {
      "handler": "smartcam",
      "commands": [
        "start_stream",
        "stop_stream",
        "start_all",
        "stop_all"
      ]
    },
    "sensehat/pi3/control": {
      "handler": "sensehat"
    }
  },
  "statusTopic": "pi3/monitor/status"
}
```

## 6. SmartCam handler responsibilities
The SmartCam handler should:
- start the RTSP stream stack
- stop the RTSP stream stack
- report status to MQTT
- eventually expose stream state health

Suggested topics:
- control: `smartcam/pi3/control`
- status: `smartcam/pi3/status`

Suggested commands:
- `start_stream`
- `stop_stream`
- `start_all`
- `stop_all`

## 7. Sense HAT handler responsibilities
The Sense HAT handler should:
- keep the existing behavior from the old Sense HAT MQTT project
- expose commands/status through its own topic space
- be implemented as one module inside this unified app

Suggested topics:
- control: `sensehat/pi3/control`
- status: `sensehat/pi3/status`

## 8. Dispatch model
Incoming message flow:
1. MQTT message arrives
2. topic is matched in config
3. payload is parsed as JSON
4. handler module is selected
5. handler executes command
6. status/result is published to configured status topic

## 9. Service model
Only one Pi-side service should run at boot:
- `pi3-mqtt-monitor.service`

This service owns the MQTT client and feature dispatching.

The service may spawn subprocesses for features like SmartCam stream start/stop, but the MQTT connection and control plane stay centralized.

## 10. Migration plan
1. Build unified monitor app and config
2. Move SmartCam start/stop logic into `handlers/smartcam.py`
3. Move Sense HAT MQTT command logic into `handlers/sensehat.py`
4. Replace separate MQTT feature services with one `pi3-mqtt-monitor.service`
5. Keep feature subprocesses only where necessary

## 11. Immediate recommendation
Implement the unified Pi-side control plane first.
Do not merge Ubuntu detector control into this same process, because that runs on a different host.

So the clean split should be:
- Pi 3: one unified MQTT monitor service for local Pi features
- Ubuntu: separate MQTT-controlled detector service

That keeps the Pi clean without forcing cross-host responsibilities into one daemon.
