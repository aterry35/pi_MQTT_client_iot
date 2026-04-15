# PI3_MQTT_Monitor

Unified Raspberry Pi 3 MQTT control project for Sense HAT and SmartCam control.

## What It Does
- runs one long-lived MQTT monitor on the Raspberry Pi 3
- subscribes to configured MQTT control topics
- dispatches messages to feature handlers
- exposes Sense HAT sensor, LED matrix, and Snake game actions
- starts and stops the SmartCam RTSP stream stack
- publishes sync and async status back to MQTT

## Main Files
- `pi3_mqtt_monitor.py`: main MQTT monitor and dispatcher
- `client.py`: MQTT client wrapper
- `sense_hat_handler.py`: Sense HAT actions and Snake game
- `smartcam_handler.py`: SmartCam stream lifecycle control
- `config.py`: config loading and defaults
- `config.example.json`: sanitized example configuration for new deployments

## Setup
1. Copy `config.example.json` to `config.json`.
2. Fill in your broker, device, and SmartCam paths.
3. Install Python dependencies required by your environment.
4. Run `python3 pi3_mqtt_monitor.py` or start it through systemd.

## MQTT Features
- `sensehat/pi3/control`
  - `read_once`
  - `show_text`
  - `blink`
  - `lights_on`
  - `lights_off`
  - `start_snake`
  - `stop_snake`
- `smartcam/pi3/control`
  - `start_stream`
  - `stop_stream`
  - `start_all`
  - `stop_all`

See `MQTT_TOPICS.md` for payload examples and status topic details.

## Security Notes
- `config.json` is intentionally excluded from version control.
- runtime logs and caches are intentionally excluded from version control.
- commit only `config.example.json` or other sanitized configuration samples.
