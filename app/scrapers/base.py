from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    html: str
    final_url: str
    backend: str
    http_status: int = 200
    detail: str | None = None
