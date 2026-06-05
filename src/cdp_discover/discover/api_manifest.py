"""Record and persist CDP CLI commands executed during discovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class APIManifestRecorder:
    """Collects CDP CLI invocations for auditability."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def record(self, service: str, operation: str, command: str, success: bool, error: Optional[str] = None):
        self.calls.append({
            "service": service,
            "operation": operation,
            "command": command,
            "success": success,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def build(self, *, environment_name: str, discovery_tier: str, profile: str) -> dict:
        services: Dict[str, int] = {}
        operations: Dict[str, int] = {}
        for call in self.calls:
            services[call["service"]] = services.get(call["service"], 0) + 1
            key = f"{call['service']}.{call['operation']}"
            operations[key] = operations.get(key, 0) + 1
        return {
            "schemaVersion": "1",
            "environmentName": environment_name,
            "discoveryTier": discovery_tier,
            "profile": profile,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "totalCalls": len(self.calls),
            "uniqueOperations": len(operations),
            "callsByService": dict(sorted(services.items())),
            "callsByOperation": dict(sorted(operations.items())),
            "calls": self.calls,
        }


def write_api_manifest(path: Path, manifest: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, ensure_ascii=False)
        fp.write("\n")
    return path
