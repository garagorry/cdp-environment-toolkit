# CDE Job Inventory: Execution Playbook

This playbook explains how to inventory every Cloudera Data Engineering (CDE) job across all
virtual clusters (VCs) of one or more CDP environments, and how to produce an upgrade-impact
assessment for Cloudera Runtime 7.3.2 / CDE 1.26+ as CSV, JSON and an executive Excel workbook.

It covers every execution option of `cdp-discover cde-inventory` and `cdp-discover cde-report`.
Replace the `<placeholders>` with your own values.

**The tool only reads.** It makes these calls:
- `cdp de list-services`, `describe-service`, `list-vcs`, `describe-vc`, and `cdp iam get-user`
- for each VC, HTTPS `GET` on its jobs API (`/jobs`, `/resources`) after getting a token from the CDE Knox endpoint

It never creates, changes or deletes anything in CDP or CDE.

---

## 1. Prerequisites

| # | Requirement | How to check |
|---|---|---|
| 1 | Python 3.9+ | `python3 --version` |
| 2 | CDP CLI 0.9.164+ installed and configured (`~/.cdp/credentials`) | `cdp --version` and `cdp iam get-user` |
| 3 | A CDP **workload password** set for the user that runs the inventory | CDP console → *User Management* → user → *Set Workload Password* |
| 4 | **DEUser** (or higher) on each CDE service to audit | CDE console → service → *Access* |
| 5 | HTTPS (443) from the run host to the CDE endpoints (`*.cloudera.site`) | See the dry run in step 3 |
| 6 | Optional: `jq`, `duckdb`, `mlr` for terminal analysis | `jq --version` |

## 2. Install

```bash
python3 -m venv ~/.venvs/cdp-discover
source ~/.venvs/cdp-discover/bin/activate
pip install -U pip cdpcli
pip install "cdp-discover[report] @ git+https://github.com/garagorry/cdp-environment-toolkit.git@v0.3.0"

cdp-discover cde-inventory --help
cdp-discover cde-report --help
```

The `[report]` extra installs `openpyxl`, which the Excel workbook needs. Without it, the
collection still writes CSV/JSON and prints the command to build the workbook later.

## 3. Pre-flight checks (no CDE API calls)

```bash
# Who am I? (the workload username is used for the CDE API)
cdp iam get-user --profile <profile> | jq -r '.user.workloadUsername'

# Which CDE services exist in the environment?
cdp de list-services --profile <profile> | jq -r '.services[] | [.environmentName, .name, .status] | @tsv'

# Dry run: list the VCs that would be audited, their jobs API URLs and token URLs
cdp-discover cde-inventory --profile <profile> --environment-name <environment> --dry-run
```

Check the dry-run output before running for real:
- Every VC you expect is listed. VCs that are being deleted, or that have no API URL, appear as `SKIP`.
- The **token URL** host matches the host of the VC's *Grafana charts* link in the CDE UI. It has the form
  `https://service.<cde-host>/gateway/authtkn/knoxtoken/api/v1/token`.

## 4. Execution options

All options accept `--profile <profile>` (default: `default`). Each run asks for the workload
password **once**, without echoing it, unless `CDE_WORKLOAD_PASSWORD` is set.

### Option A: one environment

```bash
cdp-discover cde-inventory --profile <profile> --environment-name <environment>
```

### Option B: several environments in one run

```bash
cdp-discover cde-inventory --profile <profile> \
  --environment-name <environment-1> --environment-name <environment-2>
```

### Option C: every environment in the account

```bash
cdp-discover cde-inventory --profile <profile> --all-environments
```

### Option D: only some virtual clusters

`--vc` and `--exclude-vc` take shell-style globs on the VC name and can be repeated.

```bash
cdp-discover cde-inventory --profile <profile> --environment-name <environment> \
  --vc '<prefix>-*' --exclude-vc '*-sandbox'
```

### Option E: explicit workload user and output folder

```bash
cdp-discover cde-inventory --profile <profile> --environment-name <environment> \
  --workload-user <workload-user> \
  --output-dir ./cde_reports/<environment>
```

Without `--output-dir`, output goes to `/tmp/cde_inventory_<scope>-<timestamp>/`.

### Option F: unattended (scheduler / CI)

Provide the credentials as environment variables, read from your secret store. Never put them
on the command line.

```bash
export CDE_WORKLOAD_USER="<workload-user>"
export CDE_WORKLOAD_PASSWORD="$(<command that reads the secret>)"
cdp-discover cde-inventory --profile <profile> --all-environments \
  --output-dir "./cde_reports/account-$(date +%Y%m%d)"
rc=$?
unset CDE_WORKLOAD_PASSWORD
exit $rc
```

Without a terminal, the tool cannot prompt, so it exits with an error if the password is not set.

### Option G: offline target list (reuse an earlier environment discovery)

If `cdp-discover discover` has already run for the environment, the inventory can take the
VCs from that output. No `cdp de` calls are made. The CDE jobs API is still called.

```bash
cdp-discover discover --profile <profile> --environment-name <environment> --include-services cde
cdp-discover cde-inventory --discovery-dir /tmp/discovery_env_<environment>-<timestamp> \
  --workload-user <workload-user>
```

### Option H: TLS with a private or corporate CA

TLS certificates are verified by default. If an inspection proxy re-signs traffic, pass the
corporate CA bundle:

```bash
cdp-discover cde-inventory --profile <profile> --environment-name <environment> \
  --ca-bundle /path/to/corporate-ca.pem
```

`--insecure` turns verification off. Use it only for a short diagnostic, never for production runs.

### Option I: wrapper script

`scripts/run_cde_inventory.sh` (repository checkout) checks the CLI tools, prompts for the
password, writes to `./cde_reports/<scope>-<timestamp>/` with owner-only permissions, and
prints a severity summary plus the workbook path.

```bash
scripts/run_cde_inventory.sh -h
scripts/run_cde_inventory.sh -p <profile> -n <environment>                        # dry run
scripts/run_cde_inventory.sh -p <profile> <environment>                           # one environment
scripts/run_cde_inventory.sh -p <profile> -u <workload-user> <env-1> <env-2>      # several
scripts/run_cde_inventory.sh -p <profile> -a                                      # whole account
scripts/run_cde_inventory.sh -p <profile> -a -- --exclude-vc '*-sandbox' --ca-bundle /path/ca.pem
```

Anything after `--` is passed to `cdp-discover cde-inventory` unchanged.

### Option J: Excel workbook only (rebuild or merge)

The workbook is built automatically at the end of a run (`--no-excel` skips it). To rebuild it,
or to combine several runs (for example per-environment runs, or runs from different days) into
one executive report:

```bash
cdp-discover cde-report --inventory-dir <inventory-dir>
cdp-discover cde-report \
  --inventory-dir <inventory-dir-1> --inventory-dir <inventory-dir-2> \
  --output ./cde_reports/CDE_UpgradeImpact_all.xlsx
```

### Option summary

| Need | Flags |
|---|---|
| Preview only | `--dry-run` |
| Scope | `--environment-name` (repeatable) · `--all-environments` · `--discovery-dir` |
| Narrow VCs | `--vc GLOB` · `--exclude-vc GLOB` |
| Identity | `--profile` · `--workload-user` / `CDE_WORKLOAD_USER` · `CDE_WORKLOAD_PASSWORD` |
| TLS | `--ca-bundle PEM` · `--insecure` |
| Output | `--output-dir` · `--no-excel` |
| Other | `--timeout SECONDS` (default 60) · `--debug` |

## 5. Outputs

| File | Contents |
|---|---|
| `cde_job_inventory.csv` / `.json` | One row per job: location, entry point, resources, sizing, redacted Spark conf/args, last run, assessment |
| `cde_vc_summary.csv` | Per VC: collection status and job counts by worst severity |
| `inventory_manifest.json` | Run metadata, and every VC with status `ok` / `skipped` / `failed` / `not_attempted` and the reason |
| `CDE_UpgradeImpact_<environment>.xlsx` | Executive workbook (sheets below) |

| Workbook sheet | Purpose |
|---|---|
| EXECUTIVE SUMMARY | Scope, key metrics, readiness %, jobs by severity, headlines, per-environment table, top findings |
| Virtual Clusters | Versions, image, status and severity counts per VC |
| Job Inventory | Every job, most severe first |
| Findings | One row per finding, with the recommended action |
| Remediation Plan | Backlog: one row per finding code, with jobs and VCs affected |
| Run Details | Collection status and errors per VC |
| CLI Analysis | The terminal commands of section 7 |

**Exit codes.** `cde-inventory` returns `0` when all targeted VCs were collected, and `1` when any VC
failed, was not attempted, or credentials were rejected. `cde-report` returns `0` on success and
`2` when an input is missing or openpyxl is not installed.

## 6. Reading the assessment

| Severity | Meaning | Typical action |
|---|---|---|
| **CRITICAL** | Spark 2 VC or Spark 2 custom image: the job fails on 7.3.2 | Port to Spark 3.5 on a new VC |
| **HIGH** | Spark 3.2/3.3 VC, or a python-env for Python 2/3.8 | Rebase to Spark 3.5.x, or rebuild the python-env for 3.11/3.12 |
| **MEDIUM** | VC uses the deprecated `ubi` image | Move to `securityhardened` |
| **ACTION** | JVM options invalid on JDK 17 in `extraJavaOptions` | Remove or replace them (`-XX:+UseG1GC`, `-Xlog:gc*`) |
| **INFO** | Review item: default Python change, custom image rebuild, Airflow job, unknown version | Test during the upgrade |
| **LOW** | No breaking configuration detected | Include in regression testing |

Confirm the thresholds against the CDE and Runtime 7.3.2 release notes for the exact versions
in scope before planning remediation.

## 7. Analyze from the terminal

```bash
R=<inventory-dir>
```

```bash
# KPIs: jobs, jobs ready (LOW) and readiness %
jq '{jobs: length, ready: (map(select(.max_severity=="LOW")) | length)} | .readiness_pct = (if .jobs > 0 then (.ready * 100 / .jobs | floor) else 0 end)' "$R/cde_job_inventory.json"

# Jobs by worst severity
jq -r 'group_by(.max_severity)[] | "\(.[0].max_severity)\t\(length)"' "$R/cde_job_inventory.json"

# Environment x severity
duckdb -c "SELECT environment, max_severity, count(*) AS jobs FROM read_json_auto('$R/cde_job_inventory.json') GROUP BY ALL ORDER BY ALL"

# Virtual clusters, plus Spark version / OS image per VC
mlr --icsv --opprint cat "$R/cde_vc_summary.csv"
mlr --icsv --opprint count-distinct -f virtual_cluster,vc_spark_version,vc_spark_os "$R/cde_job_inventory.csv"

# Blocking jobs (CRITICAL / HIGH)
jq -r '.[] | select(.max_severity == "CRITICAL" or .max_severity == "HIGH") | [.max_severity, .virtual_cluster, .job_name, .vc_spark_version, .finding_codes] | @tsv' "$R/cde_job_inventory.json"

# One row per finding
jq -r '.[] | [.environment, .virtual_cluster, .job_name] as $k | .upgrade_732_impact_assessment | splits("; (?=(CRITICAL|HIGH|MEDIUM|ACTION|INFO|LOW): )") | $k + [.] | @tsv' "$R/cde_job_inventory.json"

# Remediation plan: jobs and VCs per finding code
duckdb -c "SELECT code, count(*) AS jobs, count(DISTINCT virtual_cluster) AS vcs FROM (SELECT virtual_cluster, unnest(string_split(finding_codes, ',')) AS code FROM read_json_auto('$R/cde_job_inventory.json')) GROUP BY code ORDER BY jobs DESC"

# Jobs whose latest run failed
jq -r '.[] | select(.last_run_status == "failed") | [.virtual_cluster, .job_name, .last_run_id, .last_run_started] | @tsv' "$R/cde_job_inventory.json"

# VCs not collected, with the reason
jq -r '.virtual_clusters[] | select(.status != "ok") | [.label, .status, .error] | @tsv' "$R/inventory_manifest.json"

# Export blockers to CSV
duckdb -c "COPY (SELECT environment, virtual_cluster, job_name, max_severity, finding_codes FROM read_json_auto('$R/cde_job_inventory.json') WHERE max_severity IN ('CRITICAL','HIGH')) TO 'cde_blockers.csv' (HEADER)"

# Several runs at once
duckdb -c "SELECT environment, count(*) AS jobs, count(*) FILTER (WHERE max_severity = 'LOW') AS ready FROM read_json_auto('./cde_reports/*/cde_job_inventory.json', union_by_name=true) GROUP BY environment"
```

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Token request ... HTTP 401` and the run stops | The workload user or password is wrong, or the password was never set. The run stops so the account is not locked by repeated attempts. |
| `HTTP 403` from the token endpoint or the jobs API | The user lacks DEUser on that CDE service or VC |
| `CERTIFICATE_VERIFY_FAILED` | Use `--ca-bundle` (Option H) |
| VC `skipped` | The VC is being deleted, or `describe-vc` returned no API URL. See `inventory_manifest.json`. |
| Spark version `unknown` | Upgrade the CDP CLI (`pip install -U cdpcli`). Older CLIs drop newer fields. |
| `No workload password` in a scheduler | Set `CDE_WORKLOAD_PASSWORD` (Option F) |
| `Excel report skipped` | `pip install "cdp-discover[report]"`, then run `cde-report` (Option J) |
| A VC timed out | Increase `--timeout`, then check the network path to the VC host |

Add `--debug` to any command for more detail. Debug output never includes the password or tokens.

## 9. Data handling

- Reports list job names, file paths and endpoints. Treat them as internal data and share them
  only through approved channels.
- Spark conf and argument values whose key looks secret (password, secret, token, key, keytab,
  credential, …) are written as `[REDACTED]`. Review the reports before sharing anyway.
- Report files are created owner-read/write only (`0600`).
- The password is held only in memory, for the duration of the run. Tokens are never written to disk.
- When finished, unset the variables and remove old runs as your retention policy requires:
  ```bash
  unset CDE_WORKLOAD_PASSWORD CDE_WORKLOAD_USER
  rm -rf /tmp/cde_inventory_*    # or ./cde_reports/<old-run>
  ```
