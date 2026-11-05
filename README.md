# CDP Environment Toolkit

Discover Cloudera Data Platform (CDP) environment resources, generate upgrade-planning Excel
reports, and inventory CDE jobs across virtual clusters for upgrade impact.

Installable CLI: **`cdp-discover`** (Python package `cdp_discover`). This repository was formerly
[`cdp-discovery-tool`](https://github.com/garagorry/cdp-environment-toolkit); GitHub redirects old URLs.

## Install

```bash
git clone https://github.com/garagorry/cdp-environment-toolkit.git
cd cdp-environment-toolkit
pip install -e ".[report]"
```

Requirements: **Python 3.9+**, **CDP CLI ≥ 0.9.164** on `PATH` (`pip install -U cdpcli` then `cdp configure`).

> **Keep the CDP CLI current.** The CLI only prints response fields that exist in its bundled
> API model, so an older CLI silently drops newer fields. For example, CDE `describe-service`
> loses `service.version`. Discovery records the CLI version in `manifest.json` /
> `api_manifest.json` (`cdpCliVersion`, `cliOutdated`), warns when it is below the minimum,
> lists expected fields that came back empty under `missingExpectedFields`, and skips
> operations the installed CLI or form factor does not support (`skipped` in `api_manifest.json`).

## Usage

### Discover

```bash
# One environment
cdp-discover discover --environment-name <env>

# All environments in the account
cdp-discover discover

# Common flags
cdp-discover discover --environment-name <env> --full
cdp-discover discover --environment-name <env> --include-services datalake datahub cdw
cdp-discover discover --environment-name <env> --profile production --no-archive
```

Default output: `/tmp/discovery_env_<name>-<timestamp>/` (or `/tmp/discovery_account-<ts>/` for account-wide runs).

### Generate Excel

```bash
cdp-discover generate \
  --discovery-dir /tmp/discovery_env_<env>-<timestamp> \
  --cloud aws \
  --output UpgradePlanning_<env>.xlsx \
  --no-prompt
```

### CDE job inventory (multi-cluster)

Finds every CDE service and virtual cluster in the environment(s). It then reads all job
definitions from each VC's jobs API and writes a Runtime 7.3.2 / CDE 1.26+ upgrade-impact report.

```bash
# Live discovery; prompts once for the CDP workload password (or set CDE_WORKLOAD_PASSWORD)
cdp-discover cde-inventory --environment-name <env>
cdp-discover cde-inventory --environment-name dev-env --environment-name prod-env
cdp-discover cde-inventory --all-environments

# Reuse an earlier `discover` run instead of calling the CDP CLI again
cdp-discover cde-inventory --discovery-dir /tmp/discovery_env_<env>-<ts> --workload-user <wl-user>

# Preview the target VCs and token endpoints without calling any CDE API
cdp-discover cde-inventory --environment-name <env> --dry-run
```

Output goes to `/tmp/cde_inventory_<scope>-<ts>/`:
- `cde_job_inventory.csv` / `.json`: one row per job
- `cde_vc_summary.csv`: job counts per VC by worst severity
- `inventory_manifest.json`: run metadata, plus skipped or failed VCs with the reason
- `CDE_UpgradeImpact_<env>.xlsx`: executive workbook (needs the `report` extra; `--no-excel` skips it)

Rebuild or merge workbooks from existing output with `cdp-discover cde-report --inventory-dir <dir> [--inventory-dir <dir2>]`.

- Step-by-step execution options: [docs/cde-inventory-playbook.md](docs/cde-inventory-playbook.md)
- Rules, data flow and security notes: [src/cdp_discover/cde_inventory/README.md](src/cdp_discover/cde_inventory/README.md)

## Project layout (published)

```
cdp-environment-toolkit/
├── pyproject.toml
├── src/cdp_discover/       # discover + generate implementation
│   └── cde_inventory/      # cde-inventory / cde-report subcommands (see its README)
├── docs/
│   └── cde-inventory-playbook.md
├── tests/                  # pytest (pip install -e ".[dev]"; pytest)
└── scripts/
    ├── run_discovery.sh
    ├── run_cde_inventory.sh  # cde-inventory wrapper: checks, password prompt, summary
    └── sdk_coverage.py     # --local-model: check client.py calls against the installed CLI model
```

`tests/test_client_contract.py` checks every `client.py` CLI call (operation, flags, required
arguments) against the installed CDP CLI's bundled model, offline. Run it after upgrading `cdpcli`.

## Security

Discovery is read-only but output may contain **sensitive data** (CRNs, endpoints, IP allowlists). Do not commit discovery archives or reports to this repository.

Raw credential payloads (CDE kubeconfigs) are **not** written by default. Only a redacted
`*_KubeconfigMeta_*.json` is saved. Pass `--include-secrets` to also write the raw
`*_Kubeconfig_*.json`, and handle that output as a secret.

## License / issues

https://github.com/garagorry/cdp-environment-toolkit/issues
