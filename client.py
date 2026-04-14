import json
import logging
import threading
from typing import Callable, Any, Dict, Optional

import paho.mqtt.client as mqtt
from config import SystemConfig

logger = logging.getLogger(__name__)

class MQTTClientWrapper:
    def __init__(self, config: SystemConfig):
        self.config = config
        self.client = mqtt.Client(client_id=config.mqtt.client_id)
        
        if config.mqtt.username:
            self.client.username_pw_set(config.mqtt.username, config.mqtt.password)
            
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
        self.publish_lock = threading.Lock()
        
        # topic -> callback mapping
        self.callbacks: Dict[str, Callable[[mqtt.Client, Any, mqtt.MQTTMessage], None]] = {}
        self._connected_event = threading.Event()
        
    def set_callback(self, topic: str, callback: Callable):
        self.callbacks[topic] = callback
        if self._connected_event.is_set():
            self.client.subscribe(topic)
            
    def _on_connect(self, client, userdata, flags, rc):
        logger.info(f"Connected to MQTT broker with result code {rc}")
        self._connected_event.set()
        
        # Subscribe to all registered topics upon (re)connection
        for topic in self.callbacks.keys():
            self.client.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")
            
    def _on_disconnect(self, client, userdata, rc):
        self._connected_event.clear()
        if rc != 0:
            logger.warning("Unexpected disconnection. The client will try to reconnect automatically.")
            
    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        callback = self.callbacks.get(topic)
        if callback:
            try:
                callback(client, userdata, msg)
            except Exception as e:
                logger.error(f"Error handling message on topic {topic}: {e}")
        else:
            logger.warning(f"Received message on topic {topic} without an associated callback.")

    def publish(self, topic: str, payload: Any, retain: bool = False):
        with self.publish_lock:
            if not self._connected_event.is_set():
                logger.warning(f"Attempted to publish to {topic} while disconnected.")
                
            try:
                data = json.dumps(payload)
                info = self.client.publish(topic, data, retain=retain)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Failed to publish to {topic}: {mqtt.error_string(info.rc)}")
                    return False
                return True
            except Exception as e:
                logger.error(f"Failed to publish to {topic}: {e}")
                return False

    def wait_until_connected(self, timeout: Optional[float] = None) -> bool:
        return self._connected_event.wait(timeout=timeout)

    def start(self):
        # We use connect_async + loop_start so that it doesn't block
        # and automatically handles reconnection, including backoff!
        self.client.connect_async(
            self.config.mqtt.host, 
            self.config.mqtt.port, 
            self.config.mqtt.keepalive
        )
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
