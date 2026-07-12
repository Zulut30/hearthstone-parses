from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Any


_STRICT_DECIMAL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_EMBEDDED_DECIMAL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def parse_decimal(value: Any, *, embedded: bool = False) -> float | None:
    """Parse a locale-tolerant decimal without silently accepting malformed text."""
    raw = str(value or "").strip().replace(",", ".")
    match = _EMBEDDED_DECIMAL_RE.search(raw) if embedded else _STRICT_DECIMAL_RE.fullmatch(raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_percent(value: Any, *, embedded: bool = False) -> float | None:
    raw = str(value or "").strip()
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    return parse_decimal(raw, embedded=embedded)


def normalize_percent_text(value: Any) -> str | None:
    """Return a normalized percent string while preserving supplied precision."""
    raw = str(value or "").strip().replace(",", ".")
    number = raw[:-1].strip() if raw.endswith("%") else raw
    if parse_decimal(number) is None:
        return None
    return f"{number}%"


def strip_markdown_links(value: str) -> str:
    return _MARKDOWN_LINK_RE.sub(lambda match: match.group(1), value)


def extract_markdown_links(value: str) -> list[tuple[str, str]]:
    return [(label, url) for label, url in _MARKDOWN_LINK_RE.findall(value)]


def looks_like_name(
    value: str,
    *,
    skipped: Collection[str] = (),
    description_prefixes: Sequence[str] = (),
    forbidden: Collection[str] = (),
    min_length: int = 3,
    max_length: int = 80,
    reject_terminal_punctuation: bool = False,
) -> bool:
    line = value.strip()
    if line in skipped or line in forbidden or not min_length <= len(line) <= max_length:
        return False
    if not line[0].isalnum() or line[0].islower():
        return False
    if parse_percent(line) is not None or line.isdigit() or line.startswith(description_prefixes):
        return False
    if reject_terminal_punctuation and line.endswith((".", ",")):
        return False
    return True
