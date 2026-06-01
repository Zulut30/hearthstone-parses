from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FetchResult:
    html: str
    final_url: str
    backend: str
    http_status: int = 200
    detail: str | None = None
    snapshot: dict | None = None
    api_payloads: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
