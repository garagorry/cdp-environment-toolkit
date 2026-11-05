#!/usr/bin/env bash
# Run the multi-cluster CDE job inventory (cdp-discover cde-inventory) for CDP environments.
# Read-only: cdp de list/describe calls, cdp iam get-user, and GETs against each VC jobs API.
set -euo pipefail

readonly MIN_CDP_CLI_VERSION="0.9.164"

usage() {
	cat <<'EOF'
Usage: run_cde_inventory.sh [options] <environment> [<environment> ...] [-- extra cde-inventory args]
       run_cde_inventory.sh [options] -a [-- extra cde-inventory args]

Options:
  -a            Audit every environment in the account
  -p PROFILE    CDP CLI profile (default: default)
  -u USER       CDP workload user (default: looked up with `cdp iam get-user`)
  -o DIR        Reports root directory (default: ./cde_reports)
  -n            Dry run: list VCs and token URLs only, no CDE API calls
  -h            Show this help

Environment:
  CDE_WORKLOAD_PASSWORD  Workload password; prompted (no echo) when unset

Examples:
  scripts/run_cde_inventory.sh my-env
  scripts/run_cde_inventory.sh -p prod -u srv_cde_audit dev-env prod-env
  scripts/run_cde_inventory.sh -a -- --exclude-vc 'sandbox-*' --ca-bundle /etc/pki/corp-ca.pem
EOF
}

die() {
	echo "ERROR: $*" >&2
	exit 1
}

version_ge() {
	# True when $1 >= $2 (dotted versions)
	[[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

profile="default"
workload_user=""
reports_root="${PWD}/cde_reports"
all_envs=false
dry_run=false

while getopts ":ap:u:o:nh" opt; do
	case "${opt}" in
	a) all_envs=true ;;
	p) profile="${OPTARG}" ;;
	u) workload_user="${OPTARG}" ;;
	o) reports_root="${OPTARG}" ;;
	n) dry_run=true ;;
	h)
		usage
		exit 0
		;;
	:) die "option -${OPTARG} needs a value" ;;
	*) die "unknown option -${OPTARG} (see -h)" ;;
	esac
done
shift $((OPTIND - 1))

envs=()
while (($# > 0)) && [[ "$1" != "--" ]]; do
	envs+=("$1")
	shift
done
[[ "${1:-}" == "--" ]] && shift
extra_args=("$@")

if [[ "${all_envs}" == true && ${#envs[@]} -gt 0 ]]; then
	die "use either -a or environment names, not both"
fi
if [[ "${all_envs}" == false && ${#envs[@]} -eq 0 ]]; then
	usage >&2
	exit 2
fi

command -v cdp >/dev/null 2>&1 || die "CDP CLI not found on PATH (pip install -U cdpcli; cdp configure)"
command -v cdp-discover >/dev/null 2>&1 || die "cdp-discover not found on PATH (see README: Install)"

cli_version="$(cdp --version 2>&1 | head -n1 | tr -cd '0-9.')"
if [[ -n "${cli_version}" ]] && ! version_ge "${cli_version}" "${MIN_CDP_CLI_VERSION}"; then
	echo "WARNING: CDP CLI ${cli_version} < ${MIN_CDP_CLI_VERSION}; newer CDE fields may be missing." >&2
fi

args=(cde-inventory --profile "${profile}")
if [[ "${all_envs}" == true ]]; then
	args+=(--all-environments)
	scope="account"
else
	for env in "${envs[@]}"; do
		args+=(--environment-name "${env}")
	done
	scope="$(
		IFS=-
		echo "${envs[*]}"
	)"
fi
[[ -n "${workload_user}" ]] && args+=(--workload-user "${workload_user}")

if [[ "${dry_run}" == true ]]; then
	exec cdp-discover "${args[@]}" --dry-run "${extra_args[@]+"${extra_args[@]}"}"
fi

# Reports describe customer workloads: keep them owner-only
umask 077
out_dir="${reports_root}/${scope}-$(date +%Y%m%d%H%M%S)"
mkdir -p "${out_dir}"
args+=(--output-dir "${out_dir}")

password="${CDE_WORKLOAD_PASSWORD:-}"
if [[ -z "${password}" ]]; then
	read -rsp "CDP workload password${workload_user:+ for ${workload_user}}: " password
	echo
	[[ -n "${password}" ]] || die "empty workload password"
fi

status=0
CDE_WORKLOAD_PASSWORD="${password}" cdp-discover "${args[@]}" "${extra_args[@]+"${extra_args[@]}"}" || status=$?
unset password

inventory="${out_dir}/cde_job_inventory.json"
if [[ -f "${inventory}" ]] && command -v jq >/dev/null 2>&1; then
	echo
	echo "Jobs by worst severity:"
	jq -r 'group_by(.max_severity) | map("  \(.[0].max_severity): \(length)") | .[]' "${inventory}"
fi
echo
echo "Reports: ${out_dir}"
for workbook in "${out_dir}"/*.xlsx; do
	[[ -f "${workbook}" ]] && echo "Excel:   ${workbook}"
done
exit "${status}"
