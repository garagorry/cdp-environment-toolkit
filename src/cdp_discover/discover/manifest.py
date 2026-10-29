"""Write manifest.json at the root of a discovery output directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_SCHEMA_VERSION = "2"


def _cloud_platform(environment_result: Optional[dict]) -> Optional[str]:
    if not environment_result or not isinstance(environment_result, dict):
        return None
    env = environment_result.get("environment")
    if isinstance(env, dict):
        return env.get("cloudPlatform")
    return None


def build_manifest(
    *,
    environment_name: str,
    timestamp: str,
    output_dir: Path,
    results: Dict[str, Any],
    services_discovered: Dict[str, Dict[str, Any]],
    discovery_tier: str = "standard",
    cli_info: Optional[Dict[str, Any]] = None,
    missing_fields: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """Build manifest dict from orchestrator results."""
    services = [
        name
        for name, info in services_discovered.items()
        if info.get("status") == "success"
    ]

    env_result = results.get("environment") or {}
    cloud = _cloud_platform(env_result if isinstance(env_result, dict) else None)

    return {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "environmentName": environment_name,
        "timestamp": timestamp,
        "discoveryTier": discovery_tier,
        **(cli_info or {}),
        "outputDir": str(output_dir),
        "cloudPlatform": cloud,
        "services": sorted(set(services)),
        "servicesDiscovered": services_discovered,
        "missingExpectedFields": missing_fields or [],
    }


def write_manifest(path: Path, manifest: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, ensure_ascii=False)
        fp.write("\n")
    return path
