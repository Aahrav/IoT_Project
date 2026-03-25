from __future__ import annotations

import sqlite3
import pandas as pd
from src.config import get_paths

paths = get_paths()
DB_PATH = paths.data_dir / "telemetry.db"

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            timestamp DATETIME,
            device_id TEXT,
            temperature_c REAL,
            vibration_rms REAL,
            current_a REAL,
            injected_anomaly INTEGER DEFAULT 0
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_time ON telemetry (device_id, timestamp)")
    conn.commit()
    conn.close()

def insert_telemetry(df: pd.DataFrame) -> None:
    if df.empty:
        return
    conn = sqlite3.connect(DB_PATH)
    # Ensure timestamp is string for sqlite
    df_db = df.copy()
    if pd.api.types.is_datetime64_any_dtype(df_db["timestamp"]):
        df_db["timestamp"] = df_db["timestamp"].astype(str)
        
    df_db.to_sql("telemetry", conn, if_exists="append", index=False)
    conn.close()

def load_telemetry(limit: int = 5000) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT {limit}", conn)
    conn.close()
    if not df.empty:
        df = df.sort_values(by="timestamp").reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df
