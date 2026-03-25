import json
import logging
import pandas as pd
import paho.mqtt.client as mqtt
import sys
from pathlib import Path

# Fix python path to allow importing src module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import init_db, insert_telemetry

BROKER = "localhost"
PORT = 1883
TOPIC = "factory/+/telemetry"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def on_connect(client, userdata, flags, reason_code, properties):
    logging.info(f"Connected to MQTT broker with code {reason_code}")
    client.subscribe(TOPIC)
    logging.info(f"Subscribed to {TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        df = pd.DataFrame([payload])
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        
        insert_telemetry(df)
        logging.info(f"Inserted point for {payload.get('device_id')} at {payload.get('timestamp')}")
    except Exception as e:
        logging.error(f"Error processing message from {msg.topic}: {e}")

def main():
    logging.info("Initializing SQLite database...")
    init_db()
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER, PORT, 60)
    except Exception as e:
        logging.error(f"Could not connect to broker: {e}")
        return

    logging.info("Starting ingest loop (press Ctrl+C to stop)...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Ingest stopped.")

if __name__ == "__main__":
    main()
