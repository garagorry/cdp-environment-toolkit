"""Minimal stdlib HTTPS GET helper shared by the Knox token provider and the jobs API client."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional

Urlopen = Callable[..., object]


class HttpError(Exception):
    """HTTP or transport failure. ``status`` is None for network/TLS errors."""

    def __init__(self, url: str, status: Optional[int], reason: str):
        super().__init__(f"GET {url} -> {status if status is not None else 'error'}: {reason}")
        self.url = url
        self.status = status
        self.reason = reason


def build_ssl_context(ca_bundle: Optional[str] = None, insecure: bool = False) -> ssl.SSLContext:
    """TLS verification is on unless ``insecure``; ``ca_bundle`` adds a private CA."""
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=ca_bundle)


def get_json(
    url: str,
    headers: Dict[str, str],
    ssl_context: ssl.SSLContext,
    timeout: float = 60,
    urlopen: Urlopen = urllib.request.urlopen,
):
    """GET ``url`` and decode a JSON body. Raises HttpError on any failure."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Keep the body short: error pages can be large HTML documents
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001 - best effort only
            pass
        raise HttpError(url, exc.code, detail or str(exc.reason)) from None
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        raise HttpError(url, None, str(getattr(exc, "reason", exc))) from None
    try:
        return json.loads(body) if body else {}
    except ValueError:
        raise HttpError(url, None, "response is not JSON") from None
