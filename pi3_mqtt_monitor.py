#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
import sys
import threading

from config import SystemConfig
from client import MQTTClientWrapper

ROOT = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(ROOT / 'pi3_mqtt_monitor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

handlers_map = {}
config = SystemConfig.load()

def _build_status_payload(state: str, topic: str, handler_name: str, result=None, **extra) -> dict:
    """Build a consistent status payload shape used across sync and async callbacks."""
    payload = {
        'state': state,
        'topic': topic,
        'handler': handler_name,
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if result is not None:
        payload['result'] = result
        if isinstance(result, dict):
            for key, value in result.items():
                if key not in payload:
                    payload[key] = value
    payload.update(extra)
    return payload

def _make_publish_cb(client_wrapper: MQTTClientWrapper, topic: str, spec: dict, name: str):
    """Factory that creates a publish callback with properly bound variables."""
    status_topic = spec.get('statusTopic', config.global_status_topic)
    
    def publish_cb(payload: dict):
        status_payload = _build_status_payload('handled_async', topic, name, result=payload)
        client_wrapper.publish(status_topic, status_payload)
    
    return publish_cb

def _publish_monitor_online_when_connected(mqtt_wrapper: MQTTClientWrapper):
    if not mqtt_wrapper.wait_until_connected(timeout=10):
        logger.warning("MQTT broker not connected after 10 seconds; monitor_online will be published once the connection is established.")
        mqtt_wrapper.wait_until_connected()

    mqtt_wrapper.publish(config.global_status_topic, {
        'state': 'monitor_online',
        'topics': list(config.topics.keys()),
        'ts': time.strftime('%Y-%m-%d %H:%M:%S')
    })

def load_handlers(client_wrapper: MQTTClientWrapper):
    for topic, spec in config.topics.items():
        name = spec['handler']
        if name not in handlers_map:
            try:
                if name == 'sensehat':
                    from sense_hat_handler import SenseHatHandler
                    handlers_map[name] = SenseHatHandler()
                elif name == 'smartcam':
                    from smartcam_handler import SmartcamHandler
                    publish_cb = _make_publish_cb(client_wrapper, topic, spec, name)
                    handlers_map[name] = SmartcamHandler(config, publish_callback=publish_cb)
                else:
                    logger.warning(f"Unknown handler type: {name}")
            except Exception as e:
                logger.error(f"Failed to load handler {name}: {e}")

def create_message_callback(client_wrapper: MQTTClientWrapper, topic: str, spec: dict):
    def callback(client, userdata, msg):
        raw = msg.payload.decode('utf-8', 'ignore')
        logger.info(f"on_message {msg.topic} {raw}")
        
        try:
            payload = json.loads(raw)
        except Exception as e:
            if spec['handler'] == 'sensehat':
                payload = {'text': raw}
            else:
                logger.error(f"Failed to parse JSON on {msg.topic}: {e}")
                client_wrapper.publish(config.global_status_topic, {
                    'state': 'bad_json',
                    'topic': msg.topic,
                    'error': str(e)
                })
                return
                
        handler = handlers_map.get(spec['handler'])
        if not handler:
            logger.error(f"No handler instance for {spec['handler']}")
            return
            
        try:
            result = handler.handle(payload)
            status_payload = _build_status_payload('handled', msg.topic, spec['handler'], result=result)
            client_wrapper.publish(spec.get('statusTopic', config.global_status_topic), status_payload)
        except Exception as e:
            logger.exception(f"handler_error for {spec['handler']}")
            error_payload = _build_status_payload('handler_error', msg.topic, spec['handler'], error=str(e))
            client_wrapper.publish(spec.get('statusTopic', config.global_status_topic), error_payload)
            
    return callback

def main():
    logger.info("Starting PI3 MQTT Monitor...")
    
    mqtt_wrapper = MQTTClientWrapper(config)
    load_handlers(mqtt_wrapper)
    
    # Register callbacks
    for topic, spec in config.topics.items():
        cb = create_message_callback(mqtt_wrapper, topic, spec)
        mqtt_wrapper.set_callback(topic, cb)
        
    mqtt_wrapper.start()

    threading.Thread(
        target=_publish_monitor_online_when_connected,
        args=(mqtt_wrapper,),
        daemon=True,
    ).start()
    try:
        # Block main thread without busy-waiting
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt. Shutting down...")
    finally:
        mqtt_wrapper.stop()
        for name, handler in handlers_map.items():
            if hasattr(handler, 'stop'):
                try:
                    handler.stop()
                except Exception as e:
                    logger.error(f"Error stopping {name}: {e}")

if __name__ == '__main__':
    main()
