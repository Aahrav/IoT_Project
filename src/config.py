from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    docs_dir: Path
    index_dir: Path


def get_paths() -> AppPaths:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    docs_dir = root / "docs"
    index_dir = root / "index"
    return AppPaths(root=root, data_dir=data_dir, docs_dir=docs_dir, index_dir=index_dir)

