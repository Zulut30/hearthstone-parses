from __future__ import annotations

import httpx

from ..config import flaresolverr_url, request_timeout_seconds


class FlareSolverrSession:
    def __init__(self) -> None:
        self.session_id: str | None = None

    async def __aenter__(self) -> FlareSolverrSession:
        payload = {"cmd": "sessions.create"}
        timeout = httpx.Timeout(60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(flaresolverr_url(), json=payload)
            response.raise_for_status()
            body = response.json()
        if body.get("status") != "ok":
            raise RuntimeError(f"FlareSolverr sessions.create failed: {body.get('message')}")
        self.session_id = body["session"]
        return self

    async def __aexit__(self, *args: object) -> None:
        if not self.session_id:
            return
        payload = {"cmd": "sessions.destroy", "session": self.session_id}
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(flaresolverr_url(), json=payload)
        self.session_id = None


def flaresolverr_request_timeout_ms() -> int:
    return int(request_timeout_seconds() * 1000)
