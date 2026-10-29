#!/usr/bin/env python3
"""Inspect the installed CDP CLI: version and bundled API models.

The CDP CLI only emits response fields that exist in its bundled model, so an
outdated CLI silently drops newer fields (e.g. ``de describe-service`` ->
``service.version``). This module lets discovery record the CLI version, warn
when it is stale, and skip operations the installed CLI does not support.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
from typing import Dict, Optional, Tuple

# Oldest CLI known to expose every field/operation this toolkit relies on
# (e.g. ServiceDescription.version in the `de` model, the lakehouseopt service).
MIN_CDP_CLI_VERSION = "0.9.164"

# Runs under the CLI's own interpreter; emits a compact capability map:
# {service: {camelOperation: {"formFactors": [...], "params": [...], "required": [...]}}}
_DUMP_MODEL_SCRIPT = r"""
import json, os, sys
import cdpcli, yaml
loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
root = os.path.join(os.path.dirname(cdpcli.__file__), "data")
out = {}
for svc in sorted(os.listdir(root)):
    path = os.path.join(root, svc, svc + ".yaml")
    if not os.path.isfile(path):
        continue
    with open(path) as fh:
        model = yaml.load(fh, Loader=loader)
    defs = model.get("definitions") or {}
    svc_ff = model.get("x-form-factors", "public,private")
    ops = {}
    for api_path, item in (model.get("paths") or {}).items():
        post = (item or {}).get("post") or {}
        op = api_path.rsplit("/", 1)[-1]
        req = {}
        for param in post.get("parameters") or []:
            ref = ((param.get("schema") or {}).get("$ref") or "").rsplit("/", 1)[-1]
            req = defs.get(ref) or {}
        ff = post.get("x-form-factors", svc_ff)
        ops[op] = {
            "formFactors": [f.strip() for f in ff.split(",") if f.strip()],
            "params": sorted((req.get("properties") or {}).keys()),
            "required": sorted(req.get("required") or []),
        }
    out[svc] = ops
json.dump(out, sys.stdout)
"""


def parse_version(version: Optional[str]) -> Tuple[int, ...]:
    """Parse '0.9.164' (or 'cdpcli 0.9.164') into a comparable tuple."""
    if not version:
        return ()
    match = re.search(r"\d+(?:\.\d+)*", version)
    return tuple(int(p) for p in match.group(0).split(".")) if match else ()


def is_outdated(version: Optional[str], minimum: str = MIN_CDP_CLI_VERSION) -> Optional[bool]:
    """True/False when the version is known, None when it cannot be determined."""
    parsed = parse_version(version)
    if not parsed:
        return None
    return parsed < parse_version(minimum)


def kebab_to_camel(operation: str) -> str:
    parts = operation.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def get_cli_version() -> Optional[str]:
    """Return the `cdp --version` string, or None if the CLI cannot be run."""
    try:
        result = subprocess.run(
            ["cdp", "--version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0].strip() if text else None


def _cli_python() -> Optional[str]:
    """Interpreter that runs the `cdp` entry point (read from its shebang)."""
    cdp_path = shutil.which("cdp")
    if not cdp_path:
        return None
    try:
        with open(cdp_path, "r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline().strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    parts = first[2:].split()
    if not parts:
        return None
    # "#!/usr/bin/env python3" -> resolve python3 on PATH
    if os.path.basename(parts[0]) == "env" and len(parts) > 1:
        return shutil.which(parts[1])
    return parts[0]


def load_cli_model() -> Optional[Dict[str, Dict[str, dict]]]:
    """Load the installed CLI's operation map, or None if it cannot be inspected."""
    python = _cli_python()
    if not python:
        return None
    try:
        result = subprocess.run(
            [python, "-I", "-c", _DUMP_MODEL_SCRIPT],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def get_form_factor(profile: str) -> str:
    """Form factor configured for a profile in ~/.cdp/config (default: public)."""
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.expanduser("~/.cdp/config"))
    except configparser.Error:
        return "public"
    for section in (f"profile {profile}", profile):
        if parser.has_section(section):
            return parser.get(section, "form_factor", fallback="public").strip() or "public"
    return "public"
