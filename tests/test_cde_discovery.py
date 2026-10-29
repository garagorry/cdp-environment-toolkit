"""CDE discovery against a stub client (no CDP CLI or API calls)."""

import json

import pytest

from cdp_discover.discover.config import DiscoveryConfig
from cdp_discover.discover.services.cde import CDEDiscovery

ENV = "test-env"


class StubClient:
    def __init__(self, *, version="1.26.1-h1-b15"):
        self.version = version
        self.missing = []
        self.calls = []

    def note_missing_fields(self, service, resource, fields):
        if fields:
            self.missing.append((service, resource, fields))

    def list_cde_services(self):
        return {"services": [
            {"name": "svc-a", "clusterId": "cluster-a", "environmentName": ENV, "status": "ClusterCreationCompleted"},
            {"name": "other", "clusterId": "cluster-x", "environmentName": "other-env", "status": "ClusterCreationCompleted"},
        ]}, None

    def describe_cde_service(self, cluster_id):
        service = {"name": "svc-a", "clusterId": cluster_id, "environmentName": ENV}
        if self.version:
            service["version"] = self.version
        return {"service": service}, None

    def list_cde_virtual_clusters(self, cluster_id):
        return {"vcs": []}, None

    def get_cde_upgrade_status(self, cluster_id):
        return None, ("An error occurred: no upgrade info available in cluster info "
                      "(Status Code: 500; Error Code: UNKNOWN; Service: de)")

    def get_cde_kubeconfig(self, cluster_id):
        return {"kubeconfig": "apiVersion: v1\nusers:\n- user:\n    token: SECRET"}, None

    def list_cde_backups(self):
        self.calls.append("list_cde_backups")
        return {"backups": [
            {"id": 1, "clusterId": "cluster-a"},
            {"id": 2, "clusterId": "cluster-x"},
        ]}, None

    def describe_cde_backup(self, backup_id):
        return {"backup": {"id": backup_id}}, None

    def get_cde_backup_logs(self, backup_id):
        return None, "no logs"

    def get_cde_service_init_logs(self, cluster_id):
        return None, "no logs"


@pytest.fixture
def config(tmp_path):
    return DiscoveryConfig(environment_name=ENV, output_dir=str(tmp_path / "out"), append_timestamp=False)


def test_version_captured_and_upgrade_never_run(config):
    client = StubClient()
    results = CDEDiscovery(client, config).discover()

    service = results["services"][0]
    assert service["version"] == "1.26.1-h1-b15"
    assert service["upgrade_status"]["never_upgraded"] is True
    assert client.missing == []

    cde_dir = config.output_dir / "cde" / "svc-a"
    upgrade_files = list(cde_dir.glob("*_UpgradeStatus_*.json"))
    assert len(upgrade_files) == 1
    assert json.loads(upgrade_files[0].read_text())["neverUpgraded"] is True
    assert list((config.output_dir / "cde").glob("services_list_*.json"))


def test_missing_version_is_reported(config):
    client = StubClient(version=None)
    CDEDiscovery(client, config).discover()
    assert client.missing == [("cde", "svc-a", ["version"])]


def test_raw_kubeconfig_not_written_by_default(config):
    CDEDiscovery(StubClient(), config).discover()
    cde_dir = config.output_dir / "cde" / "svc-a"
    assert not list(cde_dir.glob("*_Kubeconfig_*.json"))
    meta = list(cde_dir.glob("*_KubeconfigMeta_*.json"))
    assert len(meta) == 1
    assert "SECRET" not in meta[0].read_text()


def test_raw_kubeconfig_written_with_include_secrets(tmp_path):
    config = DiscoveryConfig(
        environment_name=ENV, output_dir=str(tmp_path / "out"), append_timestamp=False, include_secrets=True
    )
    CDEDiscovery(StubClient(), config).discover()
    assert list((config.output_dir / "cde" / "svc-a").glob("*_Kubeconfig_*.json"))


def test_backups_listed_once_and_filtered_by_cluster(config):
    client = StubClient()
    CDEDiscovery(client, config).discover()
    assert client.calls.count("list_cde_backups") == 1
    backups_file = next((config.output_dir / "cde" / "svc-a").glob("*_Backups_*.json"))
    assert [b["id"] for b in json.loads(backups_file.read_text())["backups"]] == [1]
