from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SimConfig:
    n_devices: int = 5
    points_per_device: int = 1200
    seed: int = 7
    freq_minutes: int = 5


def generate_telemetry(cfg: SimConfig) -> pd.DataFrame:
    """
    Generate synthetic multi-device telemetry with a few injected anomalies.
    Columns are intentionally "simple" to keep the MVP fast.
    """
    rng = np.random.default_rng(cfg.seed)
    base_time = pd.Timestamp.now(tz="UTC").floor("min")

    rows: list[pd.DataFrame] = []
    for d in range(cfg.n_devices):
        device_id = f"device-{d+1:02d}"
        t = pd.date_range(
            end=base_time,
            periods=cfg.points_per_device,
            freq=f"{cfg.freq_minutes}min",
        )

        # Baselines differ per device.
        temp_base = 45 + 2.5 * d
        vib_base = 0.9 + 0.1 * d
        current_base = 1.8 + 0.15 * d

        # Smooth operating regime drift.
        drift = np.linspace(0, 1, cfg.points_per_device)
        temp = temp_base + 2.0 * np.sin(drift * 6.0) + rng.normal(0, 0.7, size=cfg.points_per_device)
        vib = vib_base + 0.15 * np.sin(drift * 10.0) + rng.normal(0, 0.05, size=cfg.points_per_device)
        current = current_base + 0.2 * np.sin(drift * 4.0) + rng.normal(0, 0.06, size=cfg.points_per_device)

        # Inject anomalies near the end: overheating, vibration spike, current spike.
        anomaly = np.zeros(cfg.points_per_device, dtype=int)
        for _ in range(rng.integers(2, 4)):
            start = int(rng.integers(int(cfg.points_per_device * 0.7), cfg.points_per_device - 25))
            kind = int(rng.integers(0, 3))
            length = int(rng.integers(8, 25))
            anomaly[start : start + length] = 1
            if kind == 0:
                temp[start : start + length] += rng.uniform(7, 14)
            elif kind == 1:
                vib[start : start + length] += rng.uniform(0.35, 0.8)
            else:
                current[start : start + length] += rng.uniform(0.45, 0.95)

        df = pd.DataFrame(
            {
                "timestamp": t,
                "device_id": device_id,
                "temperature_c": temp,
                "vibration_rms": vib,
                "current_a": current,
                "injected_anomaly": anomaly,
            }
        )
        rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["device_id", "timestamp"]).reset_index(drop=True)
    return out

