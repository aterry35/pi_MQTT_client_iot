# PI3 MQTT Monitor - Documentation

This document outlines all recognized MQTT topics used by the PI3 MQTT Monitor, including their specific purposes, JSON payload structures, and expected responses.

---

## 1. Global Status Monitor
**Topic:** `pi3/monitor/status`
**Role:** This topic emits generic global lifecycle events about the Python monitor application itself (e.g. startup, error parsing JSON). It relies on one-way communication from the Raspberry Pi to the MQTT Broker.

**Examples emitted by the Pi:**
- Application startup sequence completed:
  ```json
  {
    "state": "monitor_online",
    "topics": [
      "smartcam/pi3/control",
      "sensehat/pi3/control"
    ],
    "ts": "2026-04-12 14:30:00"
  }
  ```
- Error reading an invalid JSON command payload:
  ```json
  {
    "state": "bad_json",
    "topic": "smartcam/pi3/control",
    "error": "Expecting value: line 1 column 1 (char 0)"
  }
  ```

---

## 2. Sense HAT Control
**Topic:** `sensehat/pi3/control`
**Role:** Used to control the physical Sense HAT module on the Raspberry Pi. This includes turning the LED matrix on/off, scrolling text messages, playing the Snake game, and taking environmental readings. 
**Response Topic:** Returns results to `sensehat/pi3/status`

**Available Commands & Examples:**

### Read Sensors
Reads temperature, humidity, pressure, and accelerometer/gyroscope data.
**Payload:**
```json
{
  "action": "read_once"
}
```

### Show Text
Queues text to smoothly scroll across the LED matrix.
**Payload:**
```json
{
  "action": "show_text",
  "text": "Hello World!"
}
```

### Lights On / Off
Forces the LED matrix on (solid white) or shuts it down completely.
**Payload (ON):**
```json
{
  "action": "lights_on"
}
```
**Payload (OFF):**
```json
{
  "action": "lights_off"
}
```

### Start / Stop Snake Game
Boots the interactive interactive Snake game using the Sense HAT joystick.
**Payload (Start):**
```json
{
  "action": "start_snake"
}
```
**Payload (Stop):**
```json
{
  "action": "stop_snake"
}
```

---

## 3. SmartCam Control
**Topic:** `smartcam/pi3/control`
**Role:** Controls the automated V4L2 camera streaming system. Commands trigger the background processes (`mediamtx` and `ffmpeg`) to start converting the Raspberry Pi's camera feed into a consumable RTSP stream.
**Response Topic:** Returns results to `smartcam/pi3/status`

**Available Commands & Examples:**

### Start Camera Stream
Boots up the `mediamtx` server and begins feeding `ffmpeg` frames into the RTSP path. (The system will instantly return `{"state": "starting"}` and then follow up with the full running status asynchronously).
**Payload:**
```json
{
  "action": "start_stream"
}
```
**Example Async Response (from Pi):**
```json
{
  "state": "handled_async",
  "topic": "smartcam/pi3/control",
  "handler": "smartcam",
  "ts": "2026-04-12 14:32:00",
  "result": {
    "state": "running",
    "rtsp": "rtsp://RASPBERRY_PI_IP:8554/stream",
    "mediamtxPid": 1423,
    "ffmpegPid": 1424,
    "async_result": true,
    "action": "start_stream"
  }
}
```

### Stop Camera Stream
Force crashes the FFmpeg / RTSP streams to regain CPU performance and free the camera lens.
**Payload:**
```json
{
  "action": "stop_stream"
}
```
