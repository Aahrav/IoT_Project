# Edge-Fog-Cloud IoT Architecture

This project simulates a complete, end-to-end IoT software stack demonstrating Edge computing, Fog gateways, and Cloud analytics.

## Data Flow

1. **Simulated IoT Devices (`scripts/mqtt_simulator.py`)** 
   - Produces continuous live telemetry (temperature, vibration, current).
   - Publishes to `factory/<device_id>/telemetry`.

2. **Edge Node (`src/edge_agent.py`)**
   - Subscribes to the live telemetry stream (acting as if it is running on the device).
   - Performs simple, low-latency threshold-based anomaly detection.
   - If an anomaly is found, it selectively publishes an alert to `factory/<device_id>/alerts`.
   - Also subscribes to `factory/+/cmd/firmware` to accept Over-The-Air (OTA) updates to its thresholds dynamically.

3. **Fog Gateway (`fog_app.py`)**
   - Resides locally (e.g., Factory floor server).
   - Subscribes to `factory/+/alerts`.
   - Enriches alerts with localized formatting or extra metadata (e.g., location).
   - Passes data upwards (simulated here by appending to `data/fog_alerts.jsonl` which the cloud reads).

4. **Cloud / Central Analytics (`app.py`)**
   - **Ingestion**: `scripts/mqtt_ingest.py` captures all pure telemetry and dumps it efficiently into a Time-Series store (`data/telemetry.db` SQLite mapping).
   - **Dashboard**: The Streamlit interface queries the database, displays rich analytics, handles generative AI work-order synthesis (via RAG on documentation), and displays alerts forwarded by the Fog layer.
   - **Command & Control**: Provides an OTA Update UI tab where administrators can push new threshold configuration JSONs back down to Edge nodes over MQTT.

## Running the Sim

1. Start MQTT Broker: `docker-compose up -d`
2. Start the Telemetry Ingestor: `python scripts/mqtt_ingest.py`
3. Start the Device Simulator: `python scripts/mqtt_simulator.py`
4. Start the Edge Agent: `python src/edge_agent.py`
5. Start the Fog Gateway App: `streamlit run fog_app.py --server.port 8502`
6. Start the Main Cloud Dashboard: `streamlit run app.py` 

Enjoy your fully functional IoT system!
