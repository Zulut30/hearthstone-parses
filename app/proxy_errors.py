from __future__ import annotations


class ProxyPaymentRequiredError(RuntimeError):
    """Proxy returned HTTP 407 (payment required / auth failure)."""
