#!/usr/bin/env python3
"""
mitmproxy addon: log GraphQL and JSON API calls (HSReplay / HSGuru discovery).

Usage:
  mitmdump -s scripts/mitmproxy_graphql_capture.py --listen-port 8080
  # Point browser or Playwright at http://127.0.0.1:8080 with mitm CA installed.

See: https://github.com/mitmproxy/mitmproxy
"""

from __future__ import annotations

import json
from pathlib import Path

from mitmproxy import http

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "mitmproxy_captures.jsonl"
HOST_HINTS = ("hsreplay.net", "hsguru.com", "hs-manacost", "firestone")


def _interesting(host: str) -> bool:
    h = host.lower()
    return any(x in h for x in HOST_HINTS)


def _snippet(body: bytes | None, limit: int = 4000) -> str:
    if not body:
        return ""
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit]


class GraphqlCapture:
    def response(self, flow: http.HTTPFlow) -> None:
        if not flow.response or not flow.request:
            return
        host = flow.request.host or ""
        if not _interesting(host):
            return
        path = flow.request.path or ""
        method = flow.request.method
        ctype = (flow.response.headers.get("content-type") or "").lower()
        is_graphql = "graphql" in path.lower() or (
            method == "POST"
            and flow.request.content
            and b"query" in (flow.request.content or b"")[:8000]
        )
        is_json = "json" in ctype or path.endswith(".json")
        if not (is_graphql or is_json):
            return

        record = {
            "host": host,
            "method": method,
            "url": flow.request.pretty_url,
            "status": flow.response.status_code,
            "request_body": _snippet(flow.request.content),
            "response_body": _snippet(flow.response.content),
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        flow.comment = f"captured graphql/json → {OUTPUT.name}"


addons = [GraphqlCapture()]
