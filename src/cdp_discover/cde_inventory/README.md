# `cde_inventory` — CDE job inventory & upgrade-impact assessment

Implements `cdp-discover cde-inventory`. It discovers every CDE virtual cluster (VC) in one or
more CDP environments, reads all job definitions from each VC's jobs API, and assesses each job
against Cloudera Runtime 7.3.2 / CDE 1.26+ breaking changes.

Standard library only. Every call it makes is a read:

| Step | Call | Notes |
|---|---|---|
| Find VCs | `cdp de list-services`, `describe-service`, `list-vcs`, `describe-vc` | Skipped with `--discovery-dir` |
| Workload user | `cdp iam get-user` → `user.workloadUsername` | Skipped with `--workload-user` / `CDE_WORKLOAD_USER` |
| Token | `GET https://service.<cde-host>/gateway/authtkn/knoxtoken/api/v1/token` (basic auth) | One per CDE service, in memory only |
| Jobs | `GET <vcApiUrl>/jobs?latestjob=true&limit=100&offset=N` | Paged until `meta.hasNext` is false |
| Resources | `GET <vcApiUrl>/resources?limit=100&offset=N` | Python envs and custom runtime images for the rules; failure is non-fatal |

## Data flow

```
targets.py ──VCTarget[]──► cli.collect() ──► api.CdeJobsApi ──► jobs + resources
   ▲  (cdp CLI or                │                 ▲
   │   discovery dir)            │                 └── auth.KnoxTokenProvider (cached per service)
   │                             ▼
   │                      report.build_row() ── rules.assess() ──► Finding[]
   │                             ▼
   └──────────────── report.write_reports() → CSV / JSON / VC summary / manifest
```

## Modules

| File | Purpose |
|---|---|
| `targets.py` | `VCTarget` model; `targets_from_cli()`, `targets_from_discovery_dir()`, `filter_targets()` |
| `auth.py` | Knox token URL derivation, `KnoxTokenProvider`, password supplier (env var or no-echo prompt) |
| `api.py` | `CdeJobsApi`: paginated GETs, one token refresh on HTTP 401 |
| `_http.py` | `get_json()` and `build_ssl_context()` (TLS verified by default, `--ca-bundle`, `--insecure`) |
| `rules.py` | Upgrade-impact rule registry (`@rule`) and `assess()` |
| `report.py` | Row builder, secret redaction, CSV/JSON writers (files created `0600`) |
| `cli.py` | Argument parsing and orchestration |
| `excel_report.py` | Executive workbook: KPIs, headlines, findings and remediation rollups, `CLI_RECIPES` |
| `report_cli.py` | `cdp-discover cde-report` (rebuilds or merges workbooks from inventory dirs) |

## Executive Excel report

`excel_report.build_workbook()` renders the data sheets with the same `write_sheet()` and `Column`
specs as `cdp-discover generate` (`generate/excel_writer.py`). The EXECUTIVE SUMMARY sheet is
laid out by hand, and severity cells get the colors in `SEVERITY_COLORS`. Sheets:

| Sheet | Built from |
|---|---|
| EXECUTIVE SUMMARY | `compute_kpis()` and `headlines()`, per-environment counts, top 10 of `_remediation_rows()` |
| Virtual Clusters | Manifest VC outcomes plus per-VC severity counts |
| Job Inventory | Inventory rows, most severe first |
| Findings | `findings_of(row)` per job, excluding `NO_BLOCKERS` |
| Remediation Plan | Findings grouped by code, with `rules.remediation_for(code)` |
| Run Details | Manifest VC outcomes of every inventory dir |
| CLI Analysis | `CLI_RECIPES`, the same commands as the runbook's "Analyze from the CLI" section |

- `findings_of()` uses each row's structured `findings` array, which 0.3.0+ writes to JSON only.
  For older inventories it falls back to `finding_codes` + `upgrade_732_impact_assessment`. Rule
  messages may contain `"; "`, so the split happens only before a `SEVERITY: ` prefix.
- `cde-inventory` builds the workbook as a best-effort last step. A missing openpyxl or a
  rendering error is logged and never fails a finished collection.
- To add a CLI recipe, append it to `CLI_RECIPES`, mirror it in the runbook README, and run it
  against a real inventory dir.

## Where the fields come from

These come from the CDE Jobs API reference. The original script assumed most of them were
top-level job fields.

- **Spark version and OS image are VC properties**: `describe-vc` → `vc.sparkVersion` and
  `vc.sparkOSName`. Job definitions do not carry them.
- Spark settings live under `job.spark`: `file`, `className`, `conf`, `driverCores`,
  `driverMemory`, `executorCores`, `executorMemory`, `numExecutors`, `pythonEnvResourceName`, `args`.
- `job.runtimeImageResourceName` points at a `custom-runtime-image` resource. Its
  `customRuntimeImage.engine` is `spark2` or `spark3`.
- `job.latestRunInfo` is the latest run. `status` is lowercase: `succeeded`, `failed`, `killed`, `running`, and so on.

## Rules

| Severity | Code | Trigger |
|---|---|---|
| CRITICAL | `SPARK2`, `SPARK2_RUNTIME_IMAGE` | VC on Spark 2, or the job's custom runtime image is a Spark 2 image |
| HIGH | `SPARK3_REBASE` | VC on Spark 3.2 / 3.3, which must rebase to 3.5.x |
| HIGH | `PYTHON_ENV_LEGACY` | python-env resource built for `python2` / `python3.8` |
| MEDIUM | `UBI_IMAGE` | VC `sparkOSName` is `ubi` |
| ACTION | `JVM_FLAG_<flag>` | Flag removed before JDK 17 in `*.extraJavaOptions` (CMS, PermGen, `PrintGC*`, …) |
| INFO | `DEFAULT_PYTHON` | PySpark job with no python-env on Spark 3.2 (default Python 3.9 → 3.11) |
| INFO | `CUSTOM_RUNTIME_IMAGE` | Custom runtime image that must be rebuilt on the 7.3.2 base |
| INFO | `AIRFLOW_JOB` | Airflow job; the Spark rules do not apply |
| INFO | `SPARK_VERSION_UNKNOWN`, `SPARK3_MINOR_UNKNOWN` | VC Spark version missing or has no minor version |
| LOW | `NO_BLOCKERS` | Nothing above matched |

> The version thresholds come from the upgrade playbook this tool replaces. Before acting on
> them, confirm them against the CDE 1.26 and Runtime 7.3.2 release notes for the exact versions in scope.

### Adding a rule

```python
@rule
def my_check(ctx: JobContext) -> List[Finding]:
    if "spark.some.removed.conf" in ctx.conf:
        return [Finding("ACTION", "REMOVED_CONF", "spark.some.removed.conf is gone in Spark 3.5; drop it.")]
    return []
```

`ctx.job` is the raw job, `ctx.target` is the `VCTarget` (VC Spark version and OS), and
`ctx.resources` maps resource name to resource. Add a test in `tests/test_cde_inventory.py`.

## Security

- The password is read from `CDE_WORKLOAD_PASSWORD` or a no-echo prompt. It is asked for once and
  never logged. Tokens are held in memory only.
- An HTTP 401 from the token endpoint stops the run, so a wrong password is not retried against every service.
- Spark conf values and job args whose key looks secret are written as `[REDACTED]`. A key looks
  secret if it contains password, secret, token, key/keytab, credential, and similar words.
- Reports are created with `0600` permissions in a `0700` directory. They still describe customer
  workloads, so keep them out of git.
