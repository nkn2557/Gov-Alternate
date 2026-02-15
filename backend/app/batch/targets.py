from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings

DEFAULT_TARGETS_FILE = Path(__file__).with_name("targets.json")


def load_targets_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("targets file must be a JSON object")
    return data


def resolve_target(data: dict[str, Any], municipality_id: str) -> dict[str, Any] | None:
    for target in data.get("targets", []):
        if target.get("municipality_id") == municipality_id:
            return target
    return None


def resolve_engine_ids(
    data: dict[str, Any], municipality_ids: Iterable[str]
) -> list[str]:
    mapping = {}
    raw = settings.VERTEX_AI_SEARCH_ENGINE_IDS
    if raw:
        for item in raw.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            key, value = item.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                mapping[key] = value

    resolved: list[str] = []
    for municipality_id in municipality_ids:
        engine_id = mapping.get(municipality_id)
        if engine_id:
            resolved.append(engine_id)

    return resolved
