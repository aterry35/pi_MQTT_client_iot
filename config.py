import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"

@dataclass
class MQTTConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    client_id: str = "pi3_monitor"
    keepalive: int = 60
    username: Optional[str] = None
    password: Optional[str] = None

@dataclass
class RTSPConfig:
    host: str = "127.0.0.1"
    port: int = 8554
    path: str = "stream"
    publishUrl: str = "rtsp://127.0.0.1:8554/stream"

@dataclass
class SmartcamConfig:
    log_dir: str = "/home/Alex/smartcam/logs"
    mediamtx_bin: str = "/home/Alex/smartcam/mediamtx/mediamtx"
    mediamtx_cfg: str = "/home/Alex/smartcam/mediamtx.yml"
    rtsp: RTSPConfig = field(default_factory=RTSPConfig)

@dataclass
class SystemConfig:
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    device: Dict[str, Any] = field(default_factory=dict)
    smartcam: SmartcamConfig = field(default_factory=SmartcamConfig)
    topics: Dict[str, Any] = field(default_factory=dict)
    global_status_topic: str = "pi3/monitor/status"

    @classmethod
    def load(cls) -> "SystemConfig":
        if not CONFIG_FILE.exists():
            return cls()
        
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            
        mqtt_data = data.get("mqtt", {})
        device_data = data.get("device", {})
        smartcam_data = data.get("smartcam", {})
        rtsp_data = smartcam_data.get("rtsp", {})
        
        mqtt_config = MQTTConfig(
            host=mqtt_data.get("host", "127.0.0.1"),
            port=mqtt_data.get("port", 1883),
            client_id=mqtt_data.get("client_id", "pi3_monitor"),
            keepalive=mqtt_data.get("keepalive", 60),
            username=mqtt_data.get("username"),
            password=mqtt_data.get("password"),
        )
        
        rtsp_host = rtsp_data.get("host", device_data.get("ip", "127.0.0.1"))
        rtsp_port = rtsp_data.get("port", 8554)
        rtsp_path = rtsp_data.get("path", "stream")
        
        rtsp_config = RTSPConfig(
            host=rtsp_host,
            port=rtsp_port,
            path=rtsp_path,
            publishUrl=rtsp_data.get("publishUrl", f"rtsp://{rtsp_host}:{rtsp_port}/{rtsp_path}")
        )
        
        smartcam_cfg = SmartcamConfig(
            log_dir=smartcam_data.get("log_dir", "/home/Alex/smartcam/logs"),
            mediamtx_bin=smartcam_data.get("mediamtx_bin", "/home/Alex/smartcam/mediamtx/mediamtx"),
            mediamtx_cfg=smartcam_data.get("mediamtx_cfg", "/home/Alex/smartcam/mediamtx.yml"),
            rtsp=rtsp_config
        )
        
        return cls(
            mqtt=mqtt_config,
            device=device_data,
            smartcam=smartcam_cfg,
            topics=data.get("topics", {}),
            global_status_topic=data.get("statusTopic", "pi3/monitor/status")
        )
