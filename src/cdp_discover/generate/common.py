"""common — small primitives reused by every parser/builder.

* ``at(path)`` walks a JSON document with a dotted path that may also use
  bracket-indexes (``freeipa.instances[0].privateIP``).
* ``humanize(...)`` and ``stringify(...)`` keep cell content readable in Excel.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Iterable, Optional, Sequence, Union

# A column accessor can be a dotted/bracket path string or a callable that
# receives the row's "record" dict and returns the cell value.
Accessor = Union[str, Callable[[dict], Any]]

_BRACKET_RE = re.compile(r"\[(\d+)\]")


def _split_path(path: str) -> list:
    """Split ``a.b[0].c[3]`` into ``["a","b",0,"c",3]``."""
    out: list = []
    for token in path.split("."):
        if not token:
            continue
        # peel off optional [N][M]... at the end of the token
        head, *idxs = re.split(r"(\[\d+\])", token)
        if head:
            out.append(head)
        for chunk in idxs:
            m = _BRACKET_RE.fullmatch(chunk)
            if m:
                out.append(int(m.group(1)))
    return out


def at(path: str, default: Any = None) -> Callable[[dict], Any]:
    """Return an accessor function that resolves a dotted/bracket path
    against any JSON-like dict, returning ``default`` (None) if any segment
    is missing. Lists addressed without an index return the list itself.
    """
    parts = _split_path(path)

    def _get(record: Any) -> Any:
        cur: Any = record
        for p in parts:
            if cur is None:
                return default
            if isinstance(p, int):
                if isinstance(cur, list) and 0 <= p < len(cur):
                    cur = cur[p]
                else:
                    return default
            else:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return default
        return cur if cur is not None else default

    return _get


def resolve(accessor: Accessor, record: dict) -> Any:
    """Resolve a string path or a callable against ``record``."""
    if callable(accessor):
        return accessor(record)
    return at(accessor)(record)


def stringify(value: Any, *, max_len: int = 32_000) -> Any:
    """Render *value* into something Excel can store as a cell.

    * datetimes pass through (openpyxl handles them natively)
    * ``None`` becomes empty
    * lists/dicts get pretty-printed JSON (truncated to ``max_len``)
    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool, datetime)):
        return value
    try:
        rendered = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    if len(rendered) > max_len:
        rendered = rendered[: max_len - 3] + "..."
    return rendered


def join_list(value: Any, sep: str = ", ", key: Optional[str] = None) -> str:
    """Produce a human-friendly comma-separated string from a list value."""
    if not isinstance(value, list):
        return stringify(value) if value is not None else ""
    if not value:
        return ""
    if key:
        return sep.join(
            stringify(v.get(key)) if isinstance(v, dict) else stringify(v)
            for v in value
        )
    return sep.join(stringify(v) for v in value)


def first(*accessors: Accessor) -> Callable[[dict], Any]:
    """Combinator: return the first non-empty accessor result."""

    def _f(record: dict) -> Any:
        for a in accessors:
            v = resolve(a, record)
            if v not in (None, "", [], {}):
                return v
        return None

    return _f


def account_id_from_crn(crn: str) -> str:
    """Pull the tenant/account UUID out of a CDP CRN string.

    CDP CRNs use 8 colon-separated segments::

        crn:cdp:<service>:<region>:<account-uuid>:<resource-type>:<resource-uuid>

    so the account UUID lives at index 4.
    """
    if not isinstance(crn, str):
        return ""
    parts = crn.split(":")
    return parts[4] if len(parts) > 4 else ""


def load_json(path: str) -> Optional[dict]:
    """Load a JSON file, returning ``None`` on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None


def parse_iso_date(value: Any) -> Any:
    """Best-effort: parse ISO-8601 strings into datetime, else passthrough.

    Excel does not allow tz-aware datetimes, so any timezone is converted
    to UTC and stripped before returning.
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return value
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)
        except (ValueError, OSError):
            dt = dt.replace(tzinfo=None)
    return dt
