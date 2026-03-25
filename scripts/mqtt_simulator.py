import time
import json
import logging
import random
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
DEVICES = ["device-01", "device-02", "device-03", "device-04", "device-05"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(BROKER, PORT, 60)
        logging.info(f"Connected to MQTT Broker at {BROKER}:{PORT}")
    except Exception as e:
        logging.error(f"Could not connect to broker: {e}")
        return

    client.loop_start()

    logging.info("Starting to simulate live telemetry...")
    while True:
        try:
            for d in DEVICES:
                payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "device_id": d,
                    "temperature_c": round(random.normalvariate(45.0, 2.0), 2),
                    "vibration_rms": round(random.normalvariate(1.0, 0.1), 3),
                    "current_a": round(random.normalvariate(2.0, 0.2), 2),
                    "injected_anomaly": 0
                }
                
                # Randomly inject anomalies
                if random.random() < 0.02:
                    payload["temperature_c"] += random.uniform(10, 20)
                    payload["injected_anomaly"] = 1
                    
                topic = f"factory/{d}/telemetry"
                client.publish(topic, json.dumps(payload))
                logging.debug(f"Published to {topic}: {payload}")
                
            time.sleep(2)
        except KeyboardInterrupt:
            break

    client.loop_stop()
    logging.info("MQTT Simulator stopped.")

if __name__ == "__main__":
    main()
