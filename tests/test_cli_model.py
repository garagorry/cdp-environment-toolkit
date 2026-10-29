"""Unit tests for CLI version handling and expected-field checks (no CLI needed)."""

from cdp_discover.discover.api_manifest import APIManifestRecorder
from cdp_discover.discover.cli_model import is_outdated, parse_version
from cdp_discover.discover.contract import model_param_to_flag
from cdp_discover.discover.utils import check_expected_fields


def test_parse_version():
    assert parse_version("0.9.164") == (0, 9, 164)
    assert parse_version("cdpcli 0.9.101 (Python 3.11)") == (0, 9, 101)
    assert parse_version(None) == ()


def test_is_outdated():
    assert is_outdated("0.9.101", "0.9.164") is True
    assert is_outdated("0.9.164", "0.9.164") is False
    assert is_outdated("0.10.0", "0.9.164") is False
    assert is_outdated(None) is None


def test_model_param_to_flag():
    assert model_param_to_flag("serviceID") == "service-id"
    assert model_param_to_flag("datahubCrn") == "datahub-crn"
    assert model_param_to_flag("clusterId") == "cluster-id"


def test_check_expected_fields():
    obj = {"version": "1.26.1-h1-b15", "clouderaManager": {"version": None}}
    assert check_expected_fields(obj, ["version"], "t") == []
    assert check_expected_fields(obj, ["clouderaManager.version", "nope.x"], "t") == [
        "clouderaManager.version",
        "nope.x",
    ]


def test_api_manifest_counts_skipped_separately():
    rec = APIManifestRecorder()
    rec.set_cli_info(version="0.9.101", minimum="0.9.164", outdated=True, form_factor="public")
    rec.record("de", "describe-service", "cmd", success=True)
    rec.record("de", "get-upgrade-status", "cmd", success=False, error="boom")
    rec.record("lakehouseopt", "list-environments", "cmd", success=False, skipped="unsupported-by-cli")
    rec.record_missing_fields("cde", "svc", ["version"])
    built = rec.build(environment_name="e", discovery_tier="standard", profile="p")
    assert built["cdpCliVersion"] == "0.9.101"
    assert built["cliOutdated"] is True
    assert built["failedCalls"] == 1
    assert built["skippedCalls"] == 1
    assert rec.missing_fields == [{"service": "cde", "resource": "svc", "fields": ["version"]}]
