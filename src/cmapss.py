from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


_CMAPSS_COLS = (
    ["unit", "cycle"]
    + ["op_set_1", "op_set_2", "op_set_3"]
    + [f"s{i}" for i in range(1, 22)]
)


@dataclass(frozen=True)
class CmapssSplit:
    name: str  # e.g. FD001
    train_path: Path
    test_path: Path
    rul_path: Path


def detect_splits(cmapss_dir: Path) -> list[CmapssSplit]:
    splits: list[CmapssSplit] = []
    for name in ["FD001", "FD002", "FD003", "FD004"]:
        train_path = cmapss_dir / f"train_{name}.txt"
        test_path = cmapss_dir / f"test_{name}.txt"
        rul_path = cmapss_dir / f"RUL_{name}.txt"
        if train_path.exists() and test_path.exists() and rul_path.exists():
            splits.append(CmapssSplit(name=name, train_path=train_path, test_path=test_path, rul_path=rul_path))
    return splits


def _read_cmapss_txt(p: Path) -> pd.DataFrame:
    """
    NASA C-MAPSS files are space-separated with possible extra spaces.
    """
    df = pd.read_csv(p, sep=r"\s+", header=None, engine="python")
    # Some distributions include trailing empty columns; trim if needed.
    if df.shape[1] > len(_CMAPSS_COLS):
        df = df.iloc[:, : len(_CMAPSS_COLS)]
    df.columns = _CMAPSS_COLS[: df.shape[1]]
    return df


def load_train(split: CmapssSplit) -> pd.DataFrame:
    df = _read_cmapss_txt(split.train_path)
    df["split"] = split.name
    df["set"] = "train"
    return df


def load_test_with_rul(split: CmapssSplit) -> pd.DataFrame:
    """
    For each unit in test set, RUL file gives remaining cycles at the *end* of test trajectory.
    We convert that into an RUL per row: RUL(row) = (max_cycle - cycle) + RUL_end.
    """
    test = _read_cmapss_txt(split.test_path)
    rul_end = pd.read_csv(split.rul_path, header=None, names=["rul_end"])
    # Units are 1..N in order in the RUL file.
    rul_end["unit"] = range(1, len(rul_end) + 1)

    max_cycle = test.groupby("unit")["cycle"].max().rename("max_cycle").reset_index()
    out = test.merge(max_cycle, on="unit", how="left").merge(rul_end[["unit", "rul_end"]], on="unit", how="left")
    out["rul"] = (out["max_cycle"] - out["cycle"]) + out["rul_end"]
    out = out.drop(columns=["max_cycle"])
    out["split"] = split.name
    out["set"] = "test"
    return out


def load_split_all(split: CmapssSplit) -> pd.DataFrame:
    train = load_train(split)
    test = load_test_with_rul(split)
    return pd.concat([train, test], ignore_index=True)

