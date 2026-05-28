"""Local JSON and Parquet storage helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from bess_pipeline.config import PROCESSED_DATA_DIR, RAW_DATA_DIR


def ensure_data_dirs(
    raw_dir: str | Path = RAW_DATA_DIR,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
) -> None:
    Path(raw_dir).mkdir(parents=True, exist_ok=True)
    Path(processed_dir).mkdir(parents=True, exist_ok=True)


def safe_name(value: str) -> str:
    return value.lower().replace("/", "-").replace(" ", "-")


def raw_path(
    endpoint: str,
    label: str,
    start: str,
    end: str,
    raw_dir: str | Path = RAW_DATA_DIR,
) -> Path:
    endpoint_name = endpoint.strip("/")
    return Path(raw_dir) / endpoint_name / f"{safe_name(label)}_{start}_{end}.json"


def processed_path(dataset: str, processed_dir: str | Path = PROCESSED_DATA_DIR) -> Path:
    return Path(processed_dir) / f"{dataset}.parquet"


def write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_frame(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def read_frame(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def append_or_replace_frame(frame: pd.DataFrame, path: Path, keys: list[str]) -> Path:
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, frame], ignore_index=True)
        if keys:
            combined = combined.drop_duplicates(subset=keys, keep="last")
    else:
        combined = frame
    return write_frame(combined, path)
