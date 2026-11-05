"""Executive Excel report for CDE job inventories (``cdp-discover cde-report``).

Reads one or more ``cde-inventory`` output directories (``cde_job_inventory.json`` +
``inventory_manifest.json``) and writes a workbook using the same sheet renderer and styling as
``cdp-discover generate`` (``generate/excel_writer.write_sheet``).

Requires the ``report`` extra (openpyxl): ``pip install "cdp-discover[report]"``.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from cdp_discover.cde_inventory.rules import SEVERITIES, remediation_for, severity_rank
from cdp_discover.generate.common import parse_iso_date

_FINDING_SPLIT = re.compile(r"; (?=(?:" + "|".join(SEVERITIES) + r"): )")

INVENTORY_JSON = "cde_job_inventory.json"
MANIFEST_JSON = "inventory_manifest.json"

SEVERITY_MEANING = {
    "CRITICAL": "Will fail on 7.3.2 without changes",
    "HIGH": "Rework required before upgrade",
    "MEDIUM": "Configuration change required",
    "ACTION": "JVM option clean-up for JDK 17",
    "INFO": "Review / test during upgrade",
    "LOW": "No blockers; regression test only",
}
# (fill, font) colors per severity
SEVERITY_COLORS = {
    "CRITICAL": ("C00000", "FFFFFF"),
    "HIGH": ("ED7D31", "FFFFFF"),
    "MEDIUM": ("FFC000", "000000"),
    "ACTION": ("7030A0", "FFFFFF"),
    "INFO": ("5B9BD5", "FFFFFF"),
    "LOW": ("70AD47", "FFFFFF"),
}

# Commands that reproduce each workbook view from the generated files (also in the runbook README).
# $R is the inventory output directory.
CLI_RECIPES: List[Tuple[str, str, str]] = [
    ("Executive KPIs", "jq",
     "jq '{jobs: length, ready: (map(select(.max_severity==\"LOW\")) | length)} "
     "| .readiness_pct = (if .jobs > 0 then (.ready * 100 / .jobs | floor) else 0 end)' \"$R/cde_job_inventory.json\""),
    ("Jobs by worst severity", "jq",
     "jq -r 'group_by(.max_severity)[] | \"\\(.[0].max_severity)\\t\\(length)\"' \"$R/cde_job_inventory.json\""),
    ("By environment x severity", "duckdb",
     "duckdb -c \"SELECT environment, max_severity, count(*) AS jobs FROM read_json_auto('$R/cde_job_inventory.json') "
     "GROUP BY ALL ORDER BY ALL\""),
    ("Virtual Clusters", "mlr", "mlr --icsv --opprint cat \"$R/cde_vc_summary.csv\""),
    ("Spark version / OS per VC", "mlr",
     "mlr --icsv --opprint count-distinct -f virtual_cluster,vc_spark_version,vc_spark_os \"$R/cde_job_inventory.csv\""),
    ("Findings (one row per finding)", "jq",
     "jq -r '.[] | [.environment, .virtual_cluster, .job_name] as $k "
     "| .upgrade_732_impact_assessment "
     "| splits(\"; (?=(CRITICAL|HIGH|MEDIUM|ACTION|INFO|LOW): )\") | $k + [.] | @tsv' \"$R/cde_job_inventory.json\""),
    ("Remediation Plan (jobs per finding code)", "duckdb",
     "duckdb -c \"SELECT code, count(*) AS jobs, count(DISTINCT virtual_cluster) AS vcs FROM "
     "(SELECT virtual_cluster, unnest(string_split(finding_codes, ',')) AS code "
     "FROM read_json_auto('$R/cde_job_inventory.json')) GROUP BY code ORDER BY jobs DESC\""),
    ("Blocking jobs (CRITICAL/HIGH)", "jq",
     "jq -r '.[] | select(.max_severity == \"CRITICAL\" or .max_severity == \"HIGH\") "
     "| [.max_severity, .virtual_cluster, .job_name, .vc_spark_version, .finding_codes] | @tsv' \"$R/cde_job_inventory.json\""),
    ("Jobs whose last run failed", "jq",
     "jq -r '.[] | select(.last_run_status == \"failed\") "
     "| [.virtual_cluster, .job_name, .last_run_id, .last_run_started] | @tsv' \"$R/cde_job_inventory.json\""),
    ("Run Details (VCs not collected)", "jq",
     "jq -r '.virtual_clusters[] | select(.status != \"ok\") | [.label, .status, .error] | @tsv' \"$R/inventory_manifest.json\""),
    ("Export blockers to CSV", "duckdb",
     "duckdb -c \"COPY (SELECT environment, virtual_cluster, job_name, max_severity, finding_codes "
     "FROM read_json_auto('$R/cde_job_inventory.json') WHERE max_severity IN ('CRITICAL','HIGH')) "
     "TO 'cde_blockers.csv' (HEADER)\""),
    ("Merge several inventory runs", "duckdb",
     "duckdb -c \"SELECT environment, count(*) AS jobs, count(*) FILTER (WHERE max_severity = 'LOW') AS ready "
     "FROM read_json_auto('/tmp/cde_inventory_*/cde_job_inventory.json', union_by_name=true) GROUP BY environment\""),
]


@dataclass
class Bundle:
    rows: List[dict] = field(default_factory=list)
    outcomes: List[dict] = field(default_factory=list)
    runs: List[dict] = field(default_factory=list)  # one manifest (minus VC list) per inventory dir


def load_inventory(dirs: Iterable[Path]) -> Bundle:
    """Merge one or more inventory output directories."""
    bundle = Bundle()
    for directory in dirs:
        directory = Path(directory)
        inventory = directory / INVENTORY_JSON
        if not inventory.is_file():
            raise FileNotFoundError(f"{inventory} not found (is this a cde-inventory output dir?)")
        rows = json.loads(inventory.read_text(encoding="utf-8"))
        manifest_path = directory / MANIFEST_JSON
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        run = {k: v for k, v in manifest.items() if k != "virtual_clusters"}
        run["inventoryDir"] = str(directory)
        bundle.runs.append(run)
        bundle.rows.extend(rows)
        for outcome in manifest.get("virtual_clusters") or []:
            bundle.outcomes.append({**outcome, "run": directory.name})
    return bundle


def findings_of(row: dict) -> List[dict]:
    """Structured findings; parsed from the flat columns for inventories that predate them."""
    if isinstance(row.get("findings"), list):
        return row["findings"]
    codes = [c for c in (row.get("finding_codes") or "").split(",") if c]
    # Messages may contain "; " themselves: only split where the next finding's severity starts
    texts = [t for t in _FINDING_SPLIT.split(row.get("upgrade_732_impact_assessment") or "") if t]
    if codes and len(codes) == len(texts):
        out = []
        for code, text in zip(codes, texts):
            severity, _, message = text.partition(": ")
            out.append({"severity": severity, "code": code, "message": message})
        return out
    return [{"severity": row.get("max_severity") or "LOW", "code": code,
             "message": row.get("upgrade_732_impact_assessment") or ""} for code in codes]


def _finding_rows(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        for f in findings_of(row):
            if f["code"] == "NO_BLOCKERS":
                continue
            out.append({**f, "environment": row.get("environment"), "cde_service": row.get("cde_service"),
                        "virtual_cluster": row.get("virtual_cluster"), "job_name": row.get("job_name"),
                        "remediation": remediation_for(f["code"])})
    return sorted(out, key=lambda f: (severity_rank(f["severity"]), f["virtual_cluster"] or "", f["job_name"] or ""))


def _remediation_rows(rows: Sequence[dict]) -> List[dict]:
    jobs: Dict[str, set] = defaultdict(set)
    vcs: Dict[str, set] = defaultdict(set)
    severity: Dict[str, str] = {}
    for row in rows:
        vc = f"{row.get('environment')}/{row.get('virtual_cluster')}"
        for f in findings_of(row):
            jobs[f["code"]].add(f"{vc}/{row.get('job_name')}")
            vcs[f["code"]].add(vc)
            severity[f["code"]] = f["severity"]
    out = [{"severity": severity[c], "code": c, "jobs": len(jobs[c]), "vcs": len(vcs[c]),
            "action": remediation_for(c)} for c in jobs]
    return sorted(out, key=lambda r: (severity_rank(r["severity"]), -r["jobs"], r["code"]))


def _vc_rows(bundle: Bundle) -> List[dict]:
    counts: Dict[str, Counter] = defaultdict(Counter)
    for row in bundle.rows:
        counts[f"{row.get('environment')}/{row.get('cde_service')}/{row.get('virtual_cluster')}"][row.get("max_severity")] += 1
    out = []
    for o in bundle.outcomes:
        c = counts.get(o.get("label"), Counter())
        out.append({**o, "jobs_total": sum(c.values()), **{s.lower(): c.get(s, 0) for s in SEVERITIES}})
    return out


def compute_kpis(bundle: Bundle) -> dict:
    by_sev = Counter(r.get("max_severity") for r in bundle.rows)
    status = Counter(o.get("status") for o in bundle.outcomes)
    total = len(bundle.rows)
    return {
        "vcs": len(bundle.outcomes),
        "vcs_ok": status.get("ok", 0),
        "vcs_failed": status.get("failed", 0) + status.get("not_attempted", 0),
        "vcs_skipped": status.get("skipped", 0),
        "jobs": total,
        "spark_jobs": sum(1 for r in bundle.rows if r.get("job_type") != "airflow"),
        "airflow_jobs": sum(1 for r in bundle.rows if r.get("job_type") == "airflow"),
        "by_severity": {s: by_sev.get(s, 0) for s in SEVERITIES},
        "blocking": by_sev.get("CRITICAL", 0) + by_sev.get("HIGH", 0),
        "readiness_pct": round(100 * by_sev.get("LOW", 0) / total, 1) if total else 0.0,
        "environments": sorted({r.get("environment") for r in bundle.rows if r.get("environment")}
                               | {o.get("environment") for o in bundle.outcomes if o.get("environment")}),
    }


def headlines(bundle: Bundle, kpis: dict) -> List[str]:
    sev = kpis["by_severity"]
    n = kpis["jobs"]
    lines = []
    if not n:
        lines.append("No CDE jobs were collected.")
    else:
        if sev["CRITICAL"]:
            lines.append(f"{sev['CRITICAL']} job(s) will fail on Runtime 7.3.2 without changes (CRITICAL).")
        if sev["HIGH"]:
            lines.append(f"{sev['HIGH']} job(s) need rework before the upgrade (HIGH): Spark 3.5 rebase or legacy Python environments.")
        if sev["MEDIUM"] or sev["ACTION"]:
            lines.append(f"{sev['MEDIUM'] + sev['ACTION']} job(s) need configuration changes (MEDIUM / ACTION).")
        if sev["LOW"] == n:
            lines.append(f"All {n} job(s) show no breaking configuration; proceed to 7.3.2 regression testing.")
        else:
            lines.append(f"{kpis['readiness_pct']}% of jobs ({sev['LOW']} of {n}) are ready for 7.3.2 testing.")
    spark = Counter()
    for o in bundle.outcomes:
        if o.get("status") == "ok":
            spark[f"{o.get('spark_version') or 'unknown'} / {o.get('spark_os') or 'unknown'}"] += 1
    if spark:
        lines.append("Spark version / image in use: " + ", ".join(f"{k} ({v} VC)" for k, v in spark.most_common()) + ".")
    if kpis["vcs_failed"]:
        lines.append(f"{kpis['vcs_failed']} virtual cluster(s) could not be collected; see Run Details.")
    if kpis["vcs_skipped"]:
        lines.append(f"{kpis['vcs_skipped']} virtual cluster(s) were skipped (not running or no API URL).")
    return lines


# --------------------------------------------------------------------------- workbook

def _columns():
    from cdp_discover.generate.columns.aws import Column

    def date(key):
        return lambda r: parse_iso_date(r.get(key))

    vc = [
        Column("Location", "Environment", "environment"),
        Column("Location", "CDE Service", "service_name"),
        Column("Location", "Virtual Cluster", "vc_name"),
        Column("Service", "CDE Version", "cde_version"),
        Column("Runtime", "Spark Version", "spark_version"),
        Column("Runtime", "OS Image", "spark_os"),
        Column("Collection", "Status", "status"),
        Column("Collection", "VC Status", "vc_status"),
        Column("Jobs", "Jobs", "jobs_total"),
        *[Column("Jobs", s.title(), s.lower()) for s in SEVERITIES],
        Column("Collection", "Error", lambda r: r.get("error") or r.get("resources_error") or ""),
        Column("Endpoint", "Jobs API URL", "vc_api_url"),
    ]
    jobs = [
        Column("Location", "Environment", "environment"),
        Column("Location", "CDE Service", "cde_service"),
        Column("Location", "Virtual Cluster", "virtual_cluster"),
        Column("Location", "Spark Version", "vc_spark_version"),
        Column("Location", "OS Image", "vc_spark_os"),
        Column("Assessment", "Worst Severity", "max_severity"),
        Column("Assessment", "Finding Codes", "finding_codes"),
        Column("Job", "Job Name", "job_name"),
        Column("Job", "Type", "job_type"),
        Column("Job", "Created", date("created")),
        Column("Job", "Modified", date("modified")),
        Column("Job", "Schedule Enabled", "schedule_enabled"),
        Column("Job", "Cron", "schedule_cron"),
        Column("Entry Point", "Application File", "application_file"),
        Column("Entry Point", "Class", "class_name"),
        Column("Entry Point", "DAG File", "dag_file"),
        Column("Resources", "Python Env", "python_env"),
        Column("Resources", "Runtime Image", "runtime_image"),
        Column("Resources", "Mounted Resources", "attached_resources"),
        Column("Sizing", "Driver Cores", "driver_cores"),
        Column("Sizing", "Driver Memory", "driver_memory"),
        Column("Sizing", "Executor Cores", "executor_cores"),
        Column("Sizing", "Executor Memory", "executor_memory"),
        Column("Sizing", "Executors", "num_executors"),
        Column("Sizing", "Min Executors", "min_executors"),
        Column("Sizing", "Max Executors", "max_executors"),
        Column("Config", "Spark Conf (redacted)", "spark_conf"),
        Column("Config", "Args (redacted)", "args"),
        Column("Last Run", "Run ID", "last_run_id"),
        Column("Last Run", "Status", "last_run_status"),
        Column("Last Run", "Started", date("last_run_started")),
        Column("Last Run", "Ended", date("last_run_ended")),
        Column("Assessment", "Impact Assessment", "upgrade_732_impact_assessment"),
    ]
    findings = [
        Column("Location", "Environment", "environment"),
        Column("Location", "Virtual Cluster", "virtual_cluster"),
        Column("Location", "Job Name", "job_name"),
        Column("Finding", "Severity", "severity"),
        Column("Finding", "Code", "code"),
        Column("Finding", "Detail", "message"),
        Column("Remediation", "Recommended Action", "remediation"),
    ]
    remediation = [
        Column("Finding", "Severity", "severity"),
        Column("Finding", "Code", "code"),
        Column("Impact", "Jobs Affected", "jobs"),
        Column("Impact", "VCs Affected", "vcs"),
        Column("Remediation", "Recommended Action", "action"),
    ]
    runs = [
        Column("Run", "Inventory Run", "run"),
        Column("Virtual Cluster", "Environment / Service / VC", "label"),
        Column("Virtual Cluster", "Status", "status"),
        Column("Virtual Cluster", "Jobs", "jobs"),
        Column("Virtual Cluster", "Resources", "resources"),
        Column("Virtual Cluster", "Error", "error"),
        Column("Virtual Cluster", "Resources Error", "resources_error"),
    ]
    cli = [
        Column("CLI", "View", "view"),
        Column("CLI", "Tool", "tool"),
        Column("CLI", "Command (set R=<inventory dir> first)", "command"),
    ]
    return vc, jobs, findings, remediation, runs, cli


def _styles():
    from openpyxl.styles import Font, PatternFill

    return {sev: (PatternFill("solid", fgColor=fill), Font(color=font, bold=True))
            for sev, (fill, font) in SEVERITY_COLORS.items()}


def colorize_severity(ws, col_idx: int, first_row: int = 3) -> None:
    """Color every severity cell in column ``col_idx`` (1-based) from ``first_row`` down."""
    styles = _styles()
    for row in range(first_row, ws.max_row + 1):
        cell = ws.cell(row=row, column=col_idx)
        style = styles.get(cell.value)
        if style:
            cell.fill, cell.font = style


def _executive_sheet(wb, bundle: Bundle, kpis: dict):
    from openpyxl.styles import Alignment, Font
    from cdp_discover.generate.excel_writer import _BORDER, _CENTER_BOLD, _LABEL_FILL, _LABEL_FONT

    ws = wb.create_sheet("EXECUTIVE SUMMARY", 0)
    styles = _styles()
    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")

    ws["A1"] = "CDE UPGRADE IMPACT - EXECUTIVE SUMMARY"
    ws["A1"].font = Font(size=16, bold=True, color="1F4E79")
    ws.merge_cells("A1:F1")
    ws["A2"] = "Target: Cloudera Runtime 7.3.2 / CDE 1.26+"
    ws["A2"].font = Font(italic=True, color="595959")

    def header(row, labels):
        for i, label in enumerate(labels, start=1):
            c = ws.cell(row=row, column=i, value=label)
            c.font, c.fill, c.alignment, c.border = _LABEL_FONT, _LABEL_FILL, _CENTER_BOLD, _BORDER

    def section(row, title):
        ws.cell(row=row, column=1, value=title).font = Font(size=12, bold=True, color="1F4E79")
        return row + 1

    last = max((r.get("finishedAt") or "" for r in bundle.runs), default="")
    meta = [
        ("Generated", _dt.datetime.now().replace(microsecond=0)),
        ("Environments", ", ".join(kpis["environments"]) or "-"),
        ("Inventory runs", f"{len(bundle.runs)} (latest finished {last or 'unknown'})"),
        ("Tool version", ", ".join(sorted({str(r.get("toolVersion")) for r in bundle.runs if r.get("toolVersion")})) or "-"),
        ("CDP CLI version", ", ".join(sorted({str(r.get("cdpCliVersion")) for r in bundle.runs if r.get("cdpCliVersion")})) or "-"),
        ("TLS verification", "on" if all(r.get("tlsVerify", True) for r in bundle.runs) else "OFF for at least one run"),
    ]
    row = 4
    for label, value in meta:
        ws.cell(row=row, column=1, value=label).font = bold
        cell = ws.cell(row=row, column=2, value=value)
        if isinstance(value, _dt.datetime):
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
        row += 1

    row = section(row + 1, "Key metrics")
    metrics = [
        ("Virtual clusters", kpis["vcs"]),
        ("  collected", kpis["vcs_ok"]),
        ("  failed / not attempted", kpis["vcs_failed"]),
        ("  skipped", kpis["vcs_skipped"]),
        ("Jobs inventoried", kpis["jobs"]),
        ("  Spark jobs", kpis["spark_jobs"]),
        ("  Airflow jobs", kpis["airflow_jobs"]),
        ("Jobs blocking the upgrade (CRITICAL + HIGH)", kpis["blocking"]),
        ("Readiness (jobs with no blockers)", kpis["readiness_pct"] / 100),
    ]
    for label, value in metrics:
        ws.cell(row=row, column=1, value=label).font = Font(bold=not label.startswith("  "))
        cell = ws.cell(row=row, column=2, value=value)
        cell.font = bold
        if label.startswith("Readiness"):
            cell.number_format = "0.0%"
        row += 1

    row = section(row + 1, "Jobs by worst severity")
    header(row, ["Severity", "Jobs", "% of jobs", "Meaning"])
    row += 1
    for sev in SEVERITIES:
        count = kpis["by_severity"][sev]
        c = ws.cell(row=row, column=1, value=sev)
        c.fill, c.font = styles[sev]
        ws.cell(row=row, column=2, value=count)
        pct = ws.cell(row=row, column=3, value=(count / kpis["jobs"]) if kpis["jobs"] else 0)
        pct.number_format = "0.0%"
        ws.cell(row=row, column=4, value=SEVERITY_MEANING[sev])
        for col in range(1, 5):
            ws.cell(row=row, column=col).border = _BORDER
        row += 1

    row = section(row + 1, "Headlines")
    for line in headlines(bundle, kpis):
        cell = ws.cell(row=row, column=1, value=f"• {line}")
        cell.alignment = wrap
        ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=6)
        ws.row_dimensions[row].height = 30
        row += 1

    row = section(row + 1, "By environment")
    header(row, ["Environment", "VCs", "Jobs", *SEVERITIES])
    row += 1
    for env in kpis["environments"]:
        env_rows = [r for r in bundle.rows if r.get("environment") == env]
        counts = Counter(r.get("max_severity") for r in env_rows)
        values = [env, sum(1 for o in bundle.outcomes if o.get("environment") == env), len(env_rows),
                  *[counts.get(s, 0) for s in SEVERITIES]]
        for col, value in enumerate(values, start=1):
            c = ws.cell(row=row, column=col, value=value)
            c.border = _BORDER
        row += 1

    row = section(row + 1, "Top findings")
    top = [r for r in _remediation_rows(bundle.rows) if r["code"] != "NO_BLOCKERS"][:10]
    if not top:
        ws.cell(row=row, column=1, value="No blocking findings.").font = Font(italic=True, color="777777")
    else:
        header(row, ["Severity", "Code", "Jobs", "VCs", "Recommended action"])
        row += 1
        for r in top:
            values = [r["severity"], r["code"], r["jobs"], r["vcs"], r["action"]]
            for col, value in enumerate(values, start=1):
                c = ws.cell(row=row, column=col, value=value)
                c.border = _BORDER
                c.alignment = wrap
            style = styles.get(r["severity"])
            if style:
                ws.cell(row=row, column=1).fill, ws.cell(row=row, column=1).font = style
            row += 1

    for letter, width in zip("ABCDEFGHI", (44, 34, 12, 40, 60, 10, 10, 10, 10)):
        ws.column_dimensions[letter].width = width
    return ws


def build_workbook(bundle: Bundle, output: Path) -> Path:
    """Write the executive workbook; returns the output path."""
    from openpyxl import Workbook
    from cdp_discover.generate.excel_writer import write_sheet

    vc_cols, job_cols, finding_cols, remediation_cols, run_cols, cli_cols = _columns()
    kpis = compute_kpis(bundle)

    wb = Workbook()
    wb.remove(wb.active)
    sheets = [
        ("Virtual Clusters", vc_cols, _vc_rows(bundle), "Status"),
        ("Job Inventory", job_cols, sorted(bundle.rows, key=lambda r: (
            severity_rank(r.get("max_severity") or "LOW"), r.get("environment") or "",
            r.get("virtual_cluster") or "", r.get("job_name") or "")), "Worst Severity"),
        ("Findings", finding_cols, _finding_rows(bundle.rows), "Severity"),
        ("Remediation Plan", remediation_cols, _remediation_rows(bundle.rows), "Severity"),
        ("Run Details", run_cols, bundle.outcomes, None),
        ("CLI Analysis", cli_cols, [{"view": v, "tool": t, "command": c} for v, t, c in CLI_RECIPES], None),
    ]
    for name, columns, records, severity_label in sheets:
        ws = write_sheet(wb, name, columns, records)
        if severity_label:
            idx = next(i for i, c in enumerate(columns, start=1) if c.label == severity_label)
            colorize_severity(ws, idx)
    vcs = wb["Virtual Clusters"]
    for sev in SEVERITIES:  # color the per-severity count headers in the VC sheet
        idx = next(i for i, c in enumerate(vc_cols, start=1) if c.label == sev.title())
        vcs.cell(row=2, column=idx).fill, vcs.cell(row=2, column=idx).font = _styles()[sev]
    wb["CLI Analysis"].column_dimensions["C"].width = 120
    _executive_sheet(wb, bundle, kpis)

    output = Path(output)
    os.makedirs(output.parent, exist_ok=True)
    wb.save(output)
    os.chmod(output, 0o600)
    return output


def default_output(bundle: Bundle, directory: Path) -> Path:
    envs = compute_kpis(bundle)["environments"]
    scope = envs[0] if len(envs) == 1 else ("multi-env" if envs else "empty")
    return Path(directory) / f"CDE_UpgradeImpact_{scope}.xlsx"
