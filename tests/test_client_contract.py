"""Offline contract test: client.py CLI calls vs. the installed CDP CLI model.

Requires the `cdp` CLI on PATH (its bundled models are read locally; no API calls).
"""

import pytest

from cdp_discover.discover.cli_model import load_cli_model
from cdp_discover.discover.contract import check_client_contract

# Pre-existing issues in --deep/--full/--exhaustive tiers, tracked for follow-up.
# Remove an entry once fixed; anything not listed here fails the test.
KNOWN_ISSUES = {
    ("collect_cod_diagnostics", "missing required --end-time"),
    ("collect_datahub_cm_diagnostics", "missing required --destination"),
    ("collect_datahub_diagnostics", "missing required --description"),
    ("collect_datahub_diagnostics", "missing required --destination"),
    ("collect_datalake_cm_diagnostics", "missing required --destination"),
    ("collect_datalake_diagnostics", "missing required --description"),
    ("collect_datalake_diagnostics", "missing required --destination"),
    ("collect_freeipa_diagnostics", "missing required --description"),
    ("collect_freeipa_diagnostics", "missing required --destination"),
    ("collect_rm_diagnostics", "operation not in CLI model"),
    ("get_cod_command_status", "operation not in CLI model"),
    ("get_dfw_deployment_configuration", "operation not in CLI model"),
    ("get_environment_operation", "missing required --environment-name"),
    ("list_cdw_configs", "operation not in CLI model"),
    ("list_compute_usage_records", "missing required --from-timestamp"),
    ("list_compute_usage_records", "missing required --to-timestamp"),
    ("list_dfw_deployment_archives", "operation not in CLI model"),
    ("list_dfw_flow_drafts", "operation not in CLI model"),
    ("list_dfw_inbound_connection_endpoints", "operation not in CLI model"),
    ("list_dfw_nifi_versions", "operation not in CLI model"),
    ("list_dfw_parameter_groups", "operation not in CLI model"),
    ("list_dfw_reporting_tasks", "operation not in CLI model"),
    ("list_ml_instance_type_configuration", "missing required --instance-category"),
    ("list_ml_instance_type_configuration", "missing required --instance-type"),
    ("list_ml_instance_type_configuration", "missing required --product-type"),
}


@pytest.fixture(scope="module")
def cli_model():
    model = load_cli_model()
    if not model:
        pytest.skip("CDP CLI not installed or its model could not be read")
    return model


def _key(issue):
    return issue.method, issue.problem.split(" (")[0]


def test_client_calls_match_cli_model(cli_model):
    issues = check_client_contract(cli_model)
    new = [str(i) for i in issues if _key(i) not in KNOWN_ISSUES]
    assert not new, "client.py calls that do not match the CDP CLI model:\n" + "\n".join(new)


def test_known_issues_still_present(cli_model):
    """Fail when a known issue gets fixed, so the allowlist is pruned."""
    current = {_key(i) for i in check_client_contract(cli_model)}
    fixed = sorted(KNOWN_ISSUES - current)
    assert not fixed, f"Remove fixed entries from KNOWN_ISSUES: {fixed}"


def test_contract_catches_wrong_flag(cli_model):
    source = '''
class C:
    def bad(self):
        return self.execute("de", "list-backups", cluster_id="x")
'''
    problems = [i.problem for i in check_client_contract(cli_model, source)]
    assert any("unknown flag --cluster-id" in p for p in problems)


def test_contract_catches_missing_required(cli_model):
    source = '''
class C:
    def bad(self):
        return self.execute("de", "get-service-init-logs", task_name="t")
'''
    problems = [i.problem for i in check_client_contract(cli_model, source)]
    assert "missing required --service-id" in problems
