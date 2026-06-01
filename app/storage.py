from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import data_dir


def root_dir() -> Path:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "datasets").mkdir(exist_ok=True)
    (root / "statuses").mkdir(exist_ok=True)
    return root


def dataset_path(source_id: str) -> Path:
    return root_dir() / "datasets" / f"{source_id}.json"


def status_path(source_id: str) -> Path:
    return root_dir() / "statuses" / f"{source_id}.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_dataset(source_id: str, payload: dict[str, Any]) -> None:
    write_json(dataset_path(source_id), payload)
    try:
        from .db import store_dataset_to_db
        store_dataset_to_db(source_id, payload)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error storing dataset {source_id} in SQLite: {e}")


def save_status(source_id: str, payload: dict[str, Any]) -> None:
    write_json(status_path(source_id), payload)


def load_dataset(source_id: str) -> dict[str, Any] | None:
    return read_json(dataset_path(source_id))


def load_status(source_id: str) -> dict[str, Any] | None:
    return read_json(status_path(source_id))
