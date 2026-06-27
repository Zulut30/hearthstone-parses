from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .source_contracts import allows_browser_fallback
from .sources import Source


@dataclass(frozen=True)
class PublishGateResult:
    ok: bool
    reason: str
    extra: dict[str, Any]


def validate_candidate_for_publish(
    source: Source,
    parsed: dict[str, Any],
    *,
    backend: str | None,
) -> PublishGateResult:
    if backend == "firecrawl" and not allows_browser_fallback(source.id, default=True):
        return PublishGateResult(
            ok=False,
            reason=(
                "backend policy rejected candidate: firecrawl is diagnostic only "
                f"for {source.id}"
            ),
            extra={"backend": backend, "backend_allowed": False},
        )

    from .scrapers.quality import validate_parsed_data

    ok, reason = validate_parsed_data(source, parsed)
    return PublishGateResult(
        ok=ok,
        reason=reason,
        extra={"backend": backend, "backend_allowed": True},
    )
