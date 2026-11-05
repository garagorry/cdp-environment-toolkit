"""Turn CDE jobs into inventory rows and write CSV / JSON / summary / manifest files."""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

from cdp_discover.cde_inventory.rules import SEVERITIES, assess, max_severity
from cdp_discover.cde_inventory.targets import VCTarget
from cdp_discover.discover.utils import is_sensitive_key

REDACTED = "[REDACTED]"
# Extra fragments for Spark conf / job args on top of the shared sensitive-key list
_EXTRA_SENSITIVE = ("keytab", "jaas", "passwd", "pwd")
_ARG_KV_RE = re.compile(r"^(--?)?([^=\s]+)=(.*)$")

INVENTORY_COLUMNS = [
    "environment", "cde_service", "cde_service_version", "virtual_cluster", "vc_id",
    "vc_api_url", "vc_spark_version", "vc_spark_os",
    "job_name", "job_type", "created", "modified", "last_used",
    "schedule_enabled", "schedule_cron",
    "application_file", "class_name", "dag_file", "python_env", "runtime_image",
    "driver_cores", "driver_memory", "executor_cores", "executor_memory", "num_executors",
    "min_executors", "max_executors",
    "attached_resources", "spark_conf", "args",
    "last_run_id", "last_run_status", "last_run_started", "last_run_ended", "last_run_user",
    "max_severity", "finding_codes", "upgrade_732_impact_assessment",
]


def _sensitive(key: str) -> bool:
    lowered = key.lower()
    return is_sensitive_key(key) or any(f in lowered for f in _EXTRA_SENSITIVE)


def redact_conf(conf: Dict[str, object]) -> Dict[str, object]:
    return {k: (REDACTED if _sensitive(str(k)) else v) for k, v in (conf or {}).items()}


def redact_args(args: Iterable[str]) -> List[str]:
    """Mask ``--password x``, ``--password=x`` and ``password=x`` style arguments."""
    out: List[str] = []
    mask_next = False
    for arg in args or []:
        arg = str(arg)
        if mask_next:
            out.append(REDACTED)
            mask_next = False
            continue
        match = _ARG_KV_RE.match(arg)
        if match and _sensitive(match.group(2)):
            out.append(f"{match.group(1) or ''}{match.group(2)}={REDACTED}")
        elif arg.startswith("-") and _sensitive(arg.lstrip("-")):
            out.append(arg)
            mask_next = True
        else:
            out.append(arg)
    return out


def build_row(job: dict, target: VCTarget, resources: Dict[str, dict]) -> dict:
    spark = job.get("spark") or {}
    airflow = job.get("airflow") or {}
    conf = spark.get("conf") or {}
    schedule = job.get("schedule") or {}
    run = job.get("latestRunInfo") or {}
    findings = assess(job, target, resources)
    mounts = [m.get("resourceName", "") for m in job.get("mounts") or []]
    return {
        "environment": target.environment,
        "cde_service": target.service_name,
        "cde_service_version": target.cde_version,
        "virtual_cluster": target.vc_name,
        "vc_id": target.vc_id,
        "vc_api_url": target.vc_api_url,
        "vc_spark_version": target.spark_version,
        "vc_spark_os": target.spark_os,
        "job_name": job.get("name"),
        "job_type": job.get("type") or "spark",
        "created": job.get("created"),
        "modified": job.get("modified"),
        "last_used": job.get("lastUsed"),
        "schedule_enabled": schedule.get("enabled"),
        "schedule_cron": schedule.get("cronExpression"),
        "application_file": spark.get("file"),
        "class_name": spark.get("className"),
        "dag_file": airflow.get("dagFile"),
        "python_env": spark.get("pythonEnvResourceName"),
        "runtime_image": job.get("runtimeImageResourceName"),
        "driver_cores": spark.get("driverCores"),
        "driver_memory": spark.get("driverMemory"),
        "executor_cores": spark.get("executorCores"),
        "executor_memory": spark.get("executorMemory"),
        "num_executors": spark.get("numExecutors"),
        "min_executors": conf.get("spark.dynamicAllocation.minExecutors"),
        "max_executors": conf.get("spark.dynamicAllocation.maxExecutors"),
        "attached_resources": ", ".join(m for m in mounts if m),
        "spark_conf": json.dumps(redact_conf(conf), sort_keys=True),
        "args": json.dumps(redact_args(spark.get("args") or [])),
        "last_run_id": run.get("id"),
        "last_run_status": run.get("status") or "never_run",
        "last_run_started": run.get("started"),
        "last_run_ended": run.get("ended"),
        "last_run_user": run.get("user"),
        "max_severity": max_severity(findings),
        "finding_codes": ",".join(f.code for f in findings),
        "upgrade_732_impact_assessment": "; ".join(f.render() for f in findings),
        # Structured copy for JSON consumers (Excel report, jq); not a CSV column
        "findings": [{"severity": f.severity, "code": f.code, "message": f.message} for f in findings],
    }


def summarize(rows: List[dict], outcomes: List[dict]) -> List[dict]:
    """One row per VC: job counts by worst severity, plus collection status."""
    by_vc: Dict[str, Counter] = {}
    for row in rows:
        key = f"{row['environment']}/{row['cde_service']}/{row['virtual_cluster']}"
        by_vc.setdefault(key, Counter())[row["max_severity"]] += 1
    summary = []
    for outcome in outcomes:
        counts = by_vc.get(outcome["label"], Counter())
        summary.append({
            "virtual_cluster": outcome["label"],
            "status": outcome["status"],
            "jobs": sum(counts.values()),
            **{sev.lower(): counts.get(sev, 0) for sev in SEVERITIES},
            "error": outcome.get("error") or "",
        })
    return summary


def _private_open(path: Path):
    """Create report files owner-read/write only (they describe customer workloads)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(fd, "w", newline="", encoding="utf-8")


def write_csv(path: Path, rows: List[dict], columns: List[str]) -> None:
    with _private_open(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data) -> None:
    with _private_open(path) as handle:
        json.dump(data, handle, indent=2, default=str)
        handle.write("\n")


def write_reports(output_dir: Path, rows: List[dict], outcomes: List[dict], manifest: dict) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = {
        "inventory_csv": output_dir / "cde_job_inventory.csv",
        "inventory_json": output_dir / "cde_job_inventory.json",
        "summary_csv": output_dir / "cde_vc_summary.csv",
        "manifest": output_dir / "inventory_manifest.json",
    }
    write_csv(paths["inventory_csv"], rows, INVENTORY_COLUMNS)
    write_json(paths["inventory_json"], rows)
    summary = summarize(rows, outcomes)
    summary_cols = ["virtual_cluster", "status", "jobs", *[s.lower() for s in SEVERITIES], "error"]
    write_csv(paths["summary_csv"], summary, summary_cols)
    write_json(paths["manifest"], {**manifest, "virtual_clusters": outcomes})
    return paths
