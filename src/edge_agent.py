import json
import logging
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
TELEMETRY_TOPIC = "factory/+/telemetry"

# Static thresholds for the edge agent to detect anomalies without hitting the db/cloud
THRESHOLDS = {
    "temperature_c": 60.0,
    "vibration_rms": 1.8,
    "current_a": 3.0
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [EDGE] %(message)s")

CMD_TOPIC = "factory/+/cmd/firmware"

def on_connect(client, userdata, flags, reason_code, properties):
    logging.info(f"Connected to MQTT broker with code {reason_code}")
    client.subscribe([(TELEMETRY_TOPIC, 0), (CMD_TOPIC, 0)])
    logging.info(f"Subscribed to {TELEMETRY_TOPIC} and {CMD_TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        
        # Handle OTA Updates
        if "cmd/firmware" in msg.topic:
            device_target = msg.topic.split("/")[1]
            logging.info(f"Received OTA update for {device_target}: {payload}")
            # Update thresholds dynamically
            for k in ["temperature_c", "vibration_rms", "current_a"]:
                if k in payload:
                    THRESHOLDS[k] = float(payload[k])
                    logging.info(f"Updated {k} threshold to {THRESHOLDS[k]}")
            return
            
        # Normal telemetry processing
        device_id = payload.get("device_id", "unknown")
        
        # Local anomaly detection
        anomalies_detected = []
        for key, threshold in THRESHOLDS.items():
            if key in payload and payload[key] > threshold:
                anomalies_detected.append(f"{key} ({payload[key]:.2f}) > {threshold}")
                
        if anomalies_detected:
            alert = {
                "device_id": device_id,
                "timestamp": payload.get("timestamp"),
                "reasons": anomalies_detected,
                "raw_payload": payload,
                "level": "critical" if len(anomalies_detected) > 1 else "warning"
            }
            alert_topic = f"factory/{device_id}/alerts"
            client.publish(alert_topic, json.dumps(alert))
            logging.warning(f"Anomaly detected for {device_id}! Published to {alert_topic}")
            
    except Exception as e:
        logging.error(f"Error processing message: {e}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER, PORT, 60)
    except Exception as e:
        logging.error(f"Could not connect to broker: {e}")
        return

    logging.info("Starting Edge Agent loop...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Edge agent stopped.")

if __name__ == "__main__":
    main()
