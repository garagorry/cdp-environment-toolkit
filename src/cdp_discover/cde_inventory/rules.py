"""Upgrade-impact rules for CDE jobs (target: Cloudera Runtime 7.3.2 / CDE 1.26+).

Each rule is a function ``(ctx: JobContext) -> list[Finding]`` registered with ``@rule``.
Add a rule by writing one function; ``assess()`` runs every registered rule in order.

The thresholds below come from the upgrade playbook this tool replaces. Verify them against
the CDE and Runtime 7.3.2 release notes for the exact versions in scope before acting on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from cdp_discover.cde_inventory.targets import VCTarget

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "ACTION", "INFO", "LOW")
_RANK = {name: i for i, name in enumerate(SEVERITIES)}

# JVM options removed or made fatal before JDK 17, with the usual replacement
REMOVED_JVM_FLAGS: Dict[str, str] = {
    "UseConcMarkSweepGC": "use -XX:+UseG1GC (CMS was removed in JDK 14)",
    "CMSInitiatingOccupancyFraction": "CMS-only flag; drop it with CMS",
    "UseCMSInitiatingOccupancyOnly": "CMS-only flag; drop it with CMS",
    "UseParNewGC": "removed in JDK 10; drop it",
    "MaxPermSize": "PermGen is gone; use -XX:MaxMetaspaceSize if needed",
    "PermSize": "PermGen is gone; use -XX:MetaspaceSize if needed",
    "AggressiveOpts": "removed in JDK 12; drop it",
    "PrintGCDateStamps": "use unified logging: -Xlog:gc*:...:time",
    "PrintGCTimeStamps": "use unified logging: -Xlog:gc*:...:uptime",
    "PrintGCDetails": "use unified logging: -Xlog:gc*",
}
_JVM_FLAG_RE = re.compile(r"-XX:[+-]?(" + "|".join(REMOVED_JVM_FLAGS) + r")\b")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.severity}: {self.message}"


@dataclass
class JobContext:
    job: dict
    target: VCTarget
    resources: Dict[str, dict] = field(default_factory=dict)

    @property
    def spark(self) -> dict:
        return self.job.get("spark") or {}

    @property
    def is_spark(self) -> bool:
        return (self.job.get("type") or "spark") == "spark"

    @property
    def conf(self) -> Dict[str, str]:
        return self.spark.get("conf") or {}

    def python_env(self) -> Optional[dict]:
        """The python-env resource the job uses, if any (named, or mounted)."""
        name = self.spark.get("pythonEnvResourceName")
        if name:
            return self.resources.get(name) or {"name": name}
        for mount in self.job.get("mounts") or []:
            resource = self.resources.get(mount.get("resourceName") or "")
            if resource and resource.get("type") == "python-env":
                return resource
        return None

    def runtime_image(self) -> Optional[dict]:
        name = self.job.get("runtimeImageResourceName")
        if not name:
            return None
        return self.resources.get(name) or {"name": name}


def parse_spark_version(value: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Accepts '3.2.3', 'SPARK3_3', 'SPARK3' and similar; returns (major, minor-or-None)."""
    if not value:
        return None, None
    match = re.search(r"(\d+)[._](\d+)", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)", value)
    return (int(match.group(1)), None) if match else (None, None)


Rule = Callable[[JobContext], List[Finding]]
RULES: List[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


@rule
def spark_engine(ctx: JobContext) -> List[Finding]:
    if not ctx.is_spark:
        return []
    image = ctx.runtime_image() or {}
    if (image.get("customRuntimeImage") or {}).get("engine") == "spark2":
        return [Finding("CRITICAL", "SPARK2_RUNTIME_IMAGE",
                        f"Custom runtime image '{image.get('name')}' is built on Spark 2; Spark 2 is removed. Rebuild on Spark 3.5.")]
    major, minor = parse_spark_version(ctx.target.spark_version)
    if major is None:
        return [Finding("INFO", "SPARK_VERSION_UNKNOWN", "VC Spark version unknown; confirm it manually.")]
    if major == 2:
        return [Finding("CRITICAL", "SPARK2", "VC runs Spark 2; Spark 2 is removed in 7.3.1+. Migrate the job to Spark 3.5.")]
    if major == 3 and minor in (2, 3):
        return [Finding("HIGH", "SPARK3_REBASE",
                        f"VC runs Spark 3.{minor}; jobs must be rebased to Spark 3.5.x on Runtime 7.3.2.")]
    if major == 3 and minor is None:
        return [Finding("INFO", "SPARK3_MINOR_UNKNOWN",
                        f"VC Spark version '{ctx.target.spark_version}' has no minor version; confirm it is 3.5.")]
    return []


@rule
def base_image(ctx: JobContext) -> List[Finding]:
    if (ctx.target.spark_os or "").lower() == "ubi":
        return [Finding("MEDIUM", "UBI_IMAGE", "VC uses the deprecated 'ubi' image; move to 'securityhardened' or a custom runtime.")]
    return []


@rule
def python_runtime(ctx: JobContext) -> List[Finding]:
    if not ctx.is_spark:
        return []
    env = ctx.python_env()
    if env:
        version = ((env.get("pythonEnv") or {}).get("pythonVersion") or "").lower()
        if version in ("python2", "python3.8"):
            return [Finding("HIGH", "PYTHON_ENV_LEGACY",
                            f"python-env '{env.get('name')}' targets {version}; rebuild it for Python 3.11/3.12.")]
        return []
    is_pyspark = (ctx.spark.get("file") or "").endswith(".py")
    major, minor = parse_spark_version(ctx.target.spark_version)
    if is_pyspark and (major, minor) == (3, 2):
        return [Finding("INFO", "DEFAULT_PYTHON",
                        "PySpark job uses the image's default Python 3.9 (Spark 3.2); 7.3.2 defaults to Python 3.11. "
                        "Test it, or attach a python-env / custom image.")]
    return []


@rule
def jvm_flags(ctx: JobContext) -> List[Finding]:
    hits = set()
    for key, value in ctx.conf.items():
        if key.endswith("extraJavaOptions") and isinstance(value, str):
            hits.update(_JVM_FLAG_RE.findall(value))
    return [
        Finding("ACTION", f"JVM_FLAG_{flag}", f"-XX:{flag} in extraJavaOptions is not valid on JDK 17: {REMOVED_JVM_FLAGS[flag]}.")
        for flag in sorted(hits)
    ]


@rule
def custom_runtime_image(ctx: JobContext) -> List[Finding]:
    image = ctx.runtime_image()
    if not image or (image.get("customRuntimeImage") or {}).get("engine") == "spark2":
        return []
    return [Finding("INFO", "CUSTOM_RUNTIME_IMAGE",
                    f"Uses custom runtime image '{image.get('name')}'; rebuild it on the 7.3.2 (JDK 17 / RHEL 9) base image.")]


@rule
def airflow_job(ctx: JobContext) -> List[Finding]:
    if ctx.job.get("type") != "airflow":
        return []
    return [Finding("INFO", "AIRFLOW_JOB",
                    "Airflow job: Spark rules do not apply; check the DAG's operators and provider versions on the target CDE version.")]


def assess(job: dict, target: VCTarget, resources: Optional[Dict[str, dict]] = None) -> List[Finding]:
    """Run every rule; returns findings sorted most-severe first, or a single LOW finding."""
    ctx = JobContext(job=job, target=target, resources=resources or {})
    findings = [f for r in RULES for f in r(ctx)]
    if not findings:
        return [Finding("LOW", "NO_BLOCKERS", "No breaking configuration detected; ready for 7.3.2 testing.")]
    return sorted(findings, key=lambda f: _RANK[f.severity])


def max_severity(findings: List[Finding]) -> str:
    return min((f.severity for f in findings), key=_RANK.__getitem__, default="LOW")


def severity_rank(severity: str) -> int:
    return _RANK.get(severity, len(SEVERITIES))


# Recommended action per finding code (JVM_FLAG_* codes share one entry via prefix match)
REMEDIATION: Dict[str, str] = {
    "SPARK2": "Create a Spark 3.5 VC on the upgraded service; port the job to Spark 3 APIs and re-test.",
    "SPARK2_RUNTIME_IMAGE": "Rebuild the custom runtime image on the Spark 3.5 dex-spark-runtime base and re-register it.",
    "SPARK3_REBASE": "Plan a Spark 3.5.x VC; re-test SQL/DataFrame behaviour changes and dependency versions.",
    "PYTHON_ENV_LEGACY": "Rebuild the python-env for Python 3.11/3.12 with pinned requirements; re-test the job.",
    "UBI_IMAGE": "Switch the VC/job to the 'securityhardened' image or a custom runtime image.",
    "JVM_FLAG_": "Remove JDK 17-invalid JVM options from extraJavaOptions (use -XX:+UseG1GC, -Xlog:gc*).",
    "DEFAULT_PYTHON": "Test the PySpark job on Python 3.11, or attach a python-env / custom image pinned to the needed version.",
    "CUSTOM_RUNTIME_IMAGE": "Rebuild the custom runtime image on the 7.3.2 (JDK 17 / RHEL 9) base image.",
    "AIRFLOW_JOB": "Validate DAG operators and provider packages against the target CDE Airflow version.",
    "SPARK_VERSION_UNKNOWN": "Confirm the VC Spark version (upgrade the CDP CLI and re-run discovery).",
    "SPARK3_MINOR_UNKNOWN": "Confirm the VC Spark minor version is 3.5.",
    "NO_BLOCKERS": "Include in the 7.3.2 regression test cycle.",
}


def remediation_for(code: str) -> str:
    if code in REMEDIATION:
        return REMEDIATION[code]
    for prefix, action in REMEDIATION.items():
        if prefix.endswith("_") and code.startswith(prefix):
            return action
    return ""
