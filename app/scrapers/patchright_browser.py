from __future__ import annotations

from ..sources import Source
from .base import FetchResult
from .browser_pool import PatchrightPool
from .proxy import assert_proxy_configured


async def fetch_via_patchright(source: Source) -> FetchResult:
    assert_proxy_configured()
    pool = await PatchrightPool.get()
    return await pool.fetch(source)


def patchright_available() -> bool:
    try:
        import patchright  # noqa: F401

        return True
    except ImportError:
        return False
