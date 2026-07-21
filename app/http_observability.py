from __future__ import annotations

import json
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping, Sequence

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
_current_request_id: ContextVar[str | None] = ContextVar(
    "http_request_id",
    default=None,
)

StructuredLogWriter = Callable[[str], None]
Clock = Callable[[], int]


def current_request_id() -> str | None:
    """Return the request ID for the current async execution context."""

    return _current_request_id.get()


def request_id_from_header(value: object) -> str:
    """Accept a bounded, log-safe request ID or generate a new UUID."""

    candidate = str(value or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


def _request_id_from_scope(scope: Mapping[str, Any]) -> str:
    values = [
        raw_value.decode("latin-1").strip()
        for raw_name, raw_value in scope.get("headers", [])
        if raw_name.lower() == b"x-request-id"
    ]
    # Multiple correlation headers are ambiguous and can be combined
    # differently by proxies. Treat them as untrusted and start a new trace.
    return request_id_from_header(values[0] if len(values) == 1 else None)


def _default_writer(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _status_class(status: int) -> str:
    return f"{max(1, min(5, status // 100))}xx"


def _route_template(scope: Mapping[str, Any], status: int) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path[:160]

    method = str(scope.get("method") or "").upper()
    headers: Sequence[tuple[bytes, bytes]] = scope.get("headers", [])
    if method == "OPTIONS" and any(
        name.lower() == b"access-control-request-method" for name, _ in headers
    ):
        return "/cors-preflight"
    if status == 404:
        return "/unmatched"
    return "/middleware"


def _error_code(error: Exception) -> str:
    raw = str(getattr(error, "code", "") or error.__class__.__name__)
    return raw if _ERROR_CODE_PATTERN.fullmatch(raw) else "UNHANDLED_ERROR"


class RequestObservabilityMiddleware:
    """Pure-ASGI request correlation and privacy-safe structured HTTP logs."""

    def __init__(
        self,
        app: Any,
        *,
        writer: StructuredLogWriter | None = None,
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        self.app = app
        self.writer = writer or _default_writer
        self.clock = clock

    def _emit(self, record: dict[str, object]) -> None:
        try:
            self.writer(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        **record,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except Exception:
            # Telemetry must never turn a healthy request into an outage.
            return

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = _current_request_id.set(request_id)
        started_at = self.clock()
        status: int | None = None

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status") or 500)
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        method = str(scope.get("method") or "UNKNOWN")[:16].upper()
        error: Exception | None = None
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as caught:
            error = caught
            status = status if status is not None and status >= 500 else 500
            self._emit(
                {
                    "event": "http_request_error",
                    "level": "error",
                    "requestId": request_id,
                    "method": method,
                    "route": _route_template(scope, status),
                    "status": status,
                    "statusClass": _status_class(status),
                    "errorName": caught.__class__.__name__[:80],
                    "errorCode": _error_code(caught),
                }
            )
            raise
        finally:
            effective_status = status if status is not None else (500 if error else 499)
            duration_ms = max(0.0, (self.clock() - started_at) / 1_000_000)
            self._emit(
                {
                    "event": "http_request",
                    "level": (
                        "error"
                        if effective_status >= 500
                        else "warn"
                        if effective_status >= 400
                        else "info"
                    ),
                    "requestId": request_id,
                    "method": method,
                    "route": _route_template(scope, effective_status),
                    "status": effective_status,
                    "statusClass": _status_class(effective_status),
                    "durationMs": round(duration_ms, 2),
                }
            )
            _current_request_id.reset(token)


async def generic_server_error(request: Request, _error: Exception) -> Response:
    """Preserve Starlette's generic 500 body while returning correlation data."""

    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str) or not _REQUEST_ID_PATTERN.fullmatch(request_id):
        request_id = request_id_from_header(request.headers.get(REQUEST_ID_HEADER))
    return PlainTextResponse(
        "Internal Server Error",
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id},
    )
