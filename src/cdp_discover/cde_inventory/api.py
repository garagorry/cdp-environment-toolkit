"""Read-only client for a CDE virtual cluster jobs API (``<vcApiUrl>`` = .../dex/api/v1)."""

from __future__ import annotations

import ssl
import urllib.request
from typing import List
from urllib.parse import urlencode

from cdp_discover.cde_inventory._http import HttpError, Urlopen, get_json
from cdp_discover.cde_inventory.targets import VCTarget

# The API caps list pages at 100 items (limit param: "up to 100")
PAGE_SIZE = 100
MAX_PAGES = 1000


class CdeJobsApi:
    def __init__(
        self,
        target: VCTarget,
        token_provider,
        ssl_context: ssl.SSLContext,
        timeout: float = 60,
        urlopen: Urlopen = urllib.request.urlopen,
    ):
        if not target.vc_api_url:
            raise ValueError(f"{target.label} has no vcApiUrl")
        self.target = target
        self.base_url = target.vc_api_url.rstrip("/")
        self._tokens = token_provider
        self._ssl_context = ssl_context
        self._timeout = timeout
        self._urlopen = urlopen

    def _get(self, path: str, params: dict):
        url = f"{self.base_url}{path}?{urlencode(params)}"
        for attempt in (1, 2):
            token = self._tokens.get(self.target, refresh=attempt == 2)
            headers = {"Authorization": f"Bearer {token}"}
            try:
                return get_json(url, headers, self._ssl_context, self._timeout, self._urlopen)
            except HttpError as exc:
                # One retry with a fresh token covers expiry during long runs
                if exc.status == 401 and attempt == 1:
                    continue
                raise

    def list_all(self, path: str, key: str, **params) -> List[dict]:
        """Follow ``limit``/``offset`` paging until ``meta.hasNext`` is false."""
        items: List[dict] = []
        offset = 0
        for _ in range(MAX_PAGES):
            doc = self._get(path, {**params, "limit": PAGE_SIZE, "offset": offset})
            if isinstance(doc, list):  # tolerate an unwrapped array
                items.extend(doc)
                return items
            page = doc.get(key) or []
            items.extend(page)
            meta = doc.get("meta")
            # Without meta we cannot tell whether limit/offset are honoured: stop after one page
            if not isinstance(meta, dict) or not meta.get("hasNext") or not page:
                return items
            offset += len(page)
        raise HttpError(f"{self.base_url}{path}", None, f"more than {MAX_PAGES} pages")

    def jobs(self) -> List[dict]:
        """All job definitions; ``latestjob=true`` adds ``latestRunInfo`` to each job."""
        return self.list_all("/jobs", "jobs", latestjob="true")

    def resources(self) -> List[dict]:
        return self.list_all("/resources", "resources")
