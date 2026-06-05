"""Shared helpers for Tier 5 diagnostic bundle collection."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from cdp_discover.discover.utils import log, save_to_file


def extract_operation_id(doc: dict) -> Optional[str]:
    """Pull async operation or command id from a collect*Diagnostics response."""
    if not isinstance(doc, dict):
        return None
    for key in ("operationId", "commandId", "jobId", "diagnosticDataJobId", "id"):
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value
    operation = doc.get("operation")
    if isinstance(operation, dict):
        return operation.get("operationId") or operation.get("id")
    return None


def save_diagnostic_collect(
    config,
    target_dir: Path,
    prefix: str,
    label: str,
    collect_doc: dict,
    exporter,
    poll_fn: Optional[Callable[[str], tuple]] = None,
) -> Optional[str]:
    """Persist a diagnostic collect response and optionally poll operation status once."""
    ts = config.timestamp
    json_path = target_dir / f"{prefix}_DiagnosticCollect_{label}_{ts}.json"
    save_to_file(collect_doc, json_path)
    exporter.save_flattened_json_to_csv(
        collect_doc,
        target_dir / f"{prefix}_DiagnosticCollect_{label}_{ts}.csv",
    )
    operation_id = extract_operation_id(collect_doc)
    if operation_id and poll_fn:
        status_doc, err = poll_fn(operation_id)
        if status_doc:
            save_to_file(
                status_doc,
                target_dir / f"{prefix}_DiagnosticOperation_{label}_{ts}.json",
            )
        elif config.debug:
            log(f"DEBUG: diagnostic operation poll {label}: {err}")
    return operation_id


def save_diagnostic_job_describes(
    config,
    target_dir: Path,
    prefix: str,
    label: str,
    jobs: list,
    describe_fn: Callable[[dict], tuple],
    exporter,
) -> None:
    """Describe each diagnostic job and write a combined sidecar."""
    if not jobs:
        return
    details = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = job.get("id") or job.get("jobId") or job.get("diagnosticDataJobId")
        if not job_id:
            details.append(job)
            continue
        describe_doc, err = describe_fn(job_id)
        if describe_doc:
            details.append(describe_doc)
        elif config.debug:
            log(f"DEBUG: diagnostic job describe {job_id}: {err}")
    if not details:
        return
    ts = config.timestamp
    path = target_dir / f"{prefix}_DiagnosticJobDescribes_{label}_{ts}.json"
    save_to_file({"diagnosticJobDetails": details}, path)
    exporter.save_instance_groups_to_csv(
        target_dir / f"{prefix}_DiagnosticJobDescribes_{label}_{ts}.csv",
        details,
    )
