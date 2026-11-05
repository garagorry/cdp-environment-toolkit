"""CDE API access tokens via the Knox token endpoint (workload user + workload password).

Documented flow (Cloudera Data Engineering, "Getting a CDE API access token"):

    GET https://<service-host>/gateway/authtkn/knoxtoken/api/v1/token   (HTTP basic auth)
    -> {"access_token": "<JWT>", ...}

``<service-host>`` is the CDE *service* host: the VC jobs API host with its first DNS label
replaced by ``service`` (the same host that serves the Grafana charts link).
"""

from __future__ import annotations

import base64
import getpass
import os
import ssl
import sys
import urllib.request
from typing import Callable, Dict, Optional
from urllib.parse import urlparse

from cdp_discover.cde_inventory._http import HttpError, Urlopen, get_json
from cdp_discover.cde_inventory.targets import VCTarget

TOKEN_PATH = "/gateway/authtkn/knoxtoken/api/v1/token"
PASSWORD_ENV = "CDE_WORKLOAD_PASSWORD"
USER_ENV = "CDE_WORKLOAD_USER"


class AuthError(Exception):
    """Token request failed. ``status`` 401/403 means bad credentials or no access."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def service_host(target: VCTarget) -> Optional[str]:
    """CDE service host for a VC, derived from vcApiUrl, else from the service clusterFqdn."""
    host = urlparse(target.vc_api_url or "").hostname
    if host and "." in host:
        return "service." + host.split(".", 1)[1]
    if target.cluster_fqdn:
        return f"service.{target.cluster_fqdn}"
    return None


def token_url(target: VCTarget) -> Optional[str]:
    host = service_host(target)
    return f"https://{host}{TOKEN_PATH}" if host else None


def password_from_env_or_prompt(user: str) -> Callable[[], str]:
    """Return a supplier that reads the password once (env var, else a no-echo prompt)."""
    cache: Dict[str, str] = {}

    def supplier() -> str:
        if "value" not in cache:
            value = os.environ.get(PASSWORD_ENV)
            if not value:
                if not sys.stdin.isatty():
                    raise AuthError(f"No workload password: set {PASSWORD_ENV} or run interactively")
                value = getpass.getpass(f"CDP workload password for {user}: ")
            if not value:
                raise AuthError("Empty workload password")
            cache["value"] = value
        return cache["value"]

    return supplier


class KnoxTokenProvider:
    """Fetches and caches one access token per CDE service host. Tokens stay in memory."""

    def __init__(
        self,
        workload_user: str,
        password_supplier: Callable[[], str],
        ssl_context: ssl.SSLContext,
        timeout: float = 30,
        urlopen: Urlopen = urllib.request.urlopen,
    ):
        self.workload_user = workload_user
        self._password = password_supplier
        self._ssl_context = ssl_context
        self._timeout = timeout
        self._urlopen = urlopen
        self._tokens: Dict[str, str] = {}

    def get(self, target: VCTarget, refresh: bool = False) -> str:
        url = token_url(target)
        if not url:
            raise AuthError(f"Cannot derive the token endpoint for {target.label}")
        if refresh or url not in self._tokens:
            self._tokens[url] = self._fetch(url)
        return self._tokens[url]

    def _fetch(self, url: str) -> str:
        raw = f"{self.workload_user}:{self._password()}".encode("utf-8")
        headers = {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}
        try:
            doc = get_json(url, headers, self._ssl_context, self._timeout, self._urlopen)
        except HttpError as exc:
            # Never echo the request headers; the URL and status are enough to troubleshoot
            raise AuthError(f"Token request to {url} failed: HTTP {exc.status}", exc.status) from None
        token = doc.get("access_token") if isinstance(doc, dict) else None
        if not token:
            raise AuthError(f"Token response from {url} has no access_token")
        return token
