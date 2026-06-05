# CDP Environment Toolkit

Discover Cloudera Data Platform (CDP) environment resources and generate upgrade-planning Excel reports.

Installable CLI: **`cdp-discover`** (Python package `cdp_discover`). This repository was formerly
[`cdp-discovery-tool`](https://github.com/garagorry/cdp-environment-toolkit); GitHub redirects old URLs.

## Install

```bash
git clone https://github.com/garagorry/cdp-environment-toolkit.git
cd cdp-environment-toolkit
pip install -e ".[report]"
```

Requirements: **Python 3.9+**, **CDP CLI** on `PATH` (`pip install cdpcli` then `cdp configure`).

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

## Project layout (published)

```
cdp-environment-toolkit/
├── pyproject.toml
├── src/cdp_discover/       # discover + generate implementation
└── scripts/run_discovery.sh
```

## Security

Discovery is read-only but output may contain **sensitive data** (CRNs, endpoints, kubeconfigs, IP allowlists). Do not commit discovery archives or reports to this repository.

## License / issues

https://github.com/garagorry/cdp-environment-toolkit/issues
