import streamlit as st
import paho.mqtt.client as mqtt
import json
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Fog Gateway Dash", layout="wide")

# We use a module-level global to share data from the MQTT background thread to the Streamlit sessions
if "alerts_store" not in st.session_state:
    st.session_state.alerts_store = []

@st.cache_resource
def get_mqtt_client():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    
    def on_connect(c, userdata, flags, rc, props):
        c.subscribe("factory/+/alerts")
        
    def on_message(c, userdata, msg):
        try:
            alert = json.loads(msg.payload.decode())
            # Enrich alert (Fog layer processing)
            alert["fog_timestamp"] = datetime.now().isoformat()
            alert["enriched_location"] = f"Factory-Floor-A (Rack {alert.get('device_id', '00')[-2:]})"
            
            # For this simple demo, we store it in a file that streamlit can read, 
            # to avoid cross-thread issues in some streamlit setups.
            with open("data/fog_alerts.jsonl", "a") as f:
                f.write(json.dumps(alert) + "\n")
                
        except Exception:
            pass
            
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("localhost", 1883, 60)
    client.loop_start()
    return client

# Ensure the MQTT client is running
_ = get_mqtt_client()

st.title("Fog Layer Gateway")
st.caption("Subscribed to edge alerts. Enriches them before sending to cloud.")

st.markdown("### Aggregated Edge Alerts")

# Read alerts from the shared file
try:
    with open("data/fog_alerts.jsonl", "r") as f:
        lines = f.readlines()
        alerts = [json.loads(l) for l in lines]
except FileNotFoundError:
    alerts = []

if alerts:
    df = pd.DataFrame(alerts)
    st.dataframe(df.sort_values(by="fog_timestamp", ascending=False), use_container_width=True)
else:
    st.info("No alerts received from edge yet. (Make sure mqtt_simulator.py and edge_agent.py are running!)")

if st.button("Refresh Alerts"):
    st.rerun()
