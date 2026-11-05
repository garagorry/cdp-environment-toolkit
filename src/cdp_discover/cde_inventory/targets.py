"""Resolve CDE virtual clusters (VCs) to audit, from the CDP CLI or a discovery output dir."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from cdp_discover.discover.utils import log

# Statuses (case-insensitive substrings) for services/VCs that cannot answer API calls
_UNUSABLE_STATUS_FRAGMENTS = ("delet",)


@dataclass
class VCTarget:
    """One CDE virtual cluster plus the service context needed to call its jobs API."""

    environment: str
    service_name: str
    cluster_id: str
    vc_name: str
    vc_id: str
    vc_api_url: Optional[str] = None
    vc_status: Optional[str] = None
    spark_version: Optional[str] = None
    spark_os: Optional[str] = None
    cluster_fqdn: Optional[str] = None
    cde_version: Optional[str] = None
    skip_reason: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{self.environment}/{self.service_name}/{self.vc_name}"

    def to_dict(self) -> dict:
        return asdict(self)


def _unusable(status: Optional[str]) -> bool:
    lowered = (status or "").lower()
    return any(fragment in lowered for fragment in _UNUSABLE_STATUS_FRAGMENTS)


def _target_from_docs(environment: str, service: dict, vc: dict) -> VCTarget:
    """Build a VCTarget from describe-service ``service`` and describe-vc ``vc`` objects."""
    target = VCTarget(
        environment=environment,
        service_name=service.get("name") or "",
        cluster_id=service.get("clusterId") or vc.get("clusterId") or "",
        vc_name=vc.get("vcName") or vc.get("vcId") or "",
        vc_id=vc.get("vcId") or "",
        vc_api_url=vc.get("vcApiUrl"),
        vc_status=vc.get("status"),
        spark_version=vc.get("sparkVersion"),
        spark_os=vc.get("sparkOSName"),
        cluster_fqdn=service.get("clusterFqdn"),
        cde_version=service.get("version"),
    )
    if not target.vc_api_url:
        target.skip_reason = "describe-vc returned no vcApiUrl"
    elif _unusable(target.vc_status):
        target.skip_reason = f"VC status {target.vc_status}"
    return target


def targets_from_cli(client, environment_names: Sequence[str]) -> List[VCTarget]:
    """
    Discover VCs live with read-only ``cdp de`` calls through a CDPClient.

    Uses list-services (account-wide, filtered by environment), describe-service,
    list-vcs and describe-vc — the same calls as ``CDEDiscovery``.
    """
    services_json, err = client.list_cde_services()
    if not services_json:
        log(f"⚠️ Could not list CDE services: {err}")
        return []

    wanted = set(environment_names)
    targets: List[VCTarget] = []
    for summary in services_json.get("services") or []:
        env = summary.get("environmentName")
        if env not in wanted:
            continue
        cluster_id = summary.get("clusterId")
        name = summary.get("name")
        if not cluster_id or _unusable(summary.get("status")):
            log(f"ℹ️ Skipping CDE service {name} (status {summary.get('status')})")
            continue

        describe, err = client.describe_cde_service(cluster_id)
        service = (describe or {}).get("service") or dict(summary)
        if not describe:
            log(f"⚠️ Could not describe CDE service {name}: {err}")

        vcs_json, err = client.list_cde_virtual_clusters(cluster_id)
        if not vcs_json:
            log(f"⚠️ Could not list virtual clusters for {name}: {err}")
            continue

        for vc_summary in vcs_json.get("vcs") or []:
            vc_id = vc_summary.get("vcId")
            if not vc_id:
                continue
            vc_doc, err = client.describe_cde_virtual_cluster(cluster_id, vc_id)
            vc = (vc_doc or {}).get("vc") or dict(vc_summary)
            if not vc_doc:
                log(f"⚠️ Could not describe VC {vc_summary.get('vcName') or vc_id}: {err}")
            targets.append(_target_from_docs(env, service, vc))

    return targets


def _latest(paths: Iterable[Path]) -> Optional[Path]:
    # Discovery file names end in a sortable %Y%m%d%H%M%S timestamp
    ordered = sorted(paths, key=lambda p: p.name)
    return ordered[-1] if ordered else None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"⚠️ Could not read {path}: {exc}")
        return None


def targets_from_discovery_dir(discovery_dir: Path) -> List[VCTarget]:
    """
    Read VCs from an existing ``cdp-discover discover`` output (single-environment or
    account-wide). Expects the layout written by ``CDEDiscovery``::

        cde/<service>/ENV_<env>_CDE_<service>_<ts>.json         -> {"service": {...}}
        cde/<service>/virtual_clusters/<vc>/vc_<vc>_<ts>.json   -> {"vc": {...}}
    """
    discovery_dir = Path(discovery_dir)
    targets: List[VCTarget] = []
    for cde_dir in sorted(p for p in discovery_dir.rglob("cde") if p.is_dir()):
        for service_dir in sorted(p for p in cde_dir.iterdir() if p.is_dir()):
            service = None
            for candidate in sorted(service_dir.glob("ENV_*_CDE_*.json"), reverse=True):
                doc = _load_json(candidate)
                if isinstance(doc, dict) and isinstance(doc.get("service"), dict):
                    service = doc["service"]
                    break
            if service is None:
                continue
            env = service.get("environmentName") or ""
            for vc_dir in sorted(p for p in (service_dir / "virtual_clusters").glob("*") if p.is_dir()):
                vc_file = _latest(vc_dir.glob("vc_*.json"))
                doc = _load_json(vc_file) if vc_file else None
                if isinstance(doc, dict) and isinstance(doc.get("vc"), dict):
                    targets.append(_target_from_docs(env, service, doc["vc"]))
    return targets


def filter_targets(
    targets: Sequence[VCTarget],
    include: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
) -> List[VCTarget]:
    """Keep VCs whose name matches any ``include`` glob and no ``exclude`` glob."""

    def matches(target: VCTarget, patterns: Sequence[str]) -> bool:
        return any(fnmatch.fnmatch(target.vc_name, p) for p in patterns)

    kept = []
    for target in targets:
        if include and not matches(target, include):
            continue
        if exclude and matches(target, exclude):
            continue
        kept.append(target)
    return kept
