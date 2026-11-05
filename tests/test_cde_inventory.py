"""CDE job inventory against stub CDP clients and a fake HTTP layer (no network, no CDP CLI)."""

import csv
import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from cdp_discover.cde_inventory import auth, report, rules
from cdp_discover.cde_inventory.api import CdeJobsApi
from cdp_discover.cde_inventory.cli import collect, main
from cdp_discover.cde_inventory.targets import (
    VCTarget,
    filter_targets,
    targets_from_cli,
    targets_from_discovery_dir,
)

ENV = "test-env"
VC_API = "https://abcd1234.cde-xyz.test-env.a1b2.cloudera.site/dex/api/v1"
TOKEN_URL = "https://service.cde-xyz.test-env.a1b2.cloudera.site/gateway/authtkn/knoxtoken/api/v1/token"


def make_target(**overrides):
    values = dict(
        environment=ENV, service_name="svc-a", cluster_id="cluster-a", vc_name="vc-dev",
        vc_id="dex-1", vc_api_url=VC_API, vc_status="AppInstalled", spark_version="SPARK3_5",
        spark_os="securityhardened", cluster_fqdn="cde-xyz.test-env.a1b2.cloudera.site",
        cde_version="1.24.1",
    )
    values.update(overrides)
    return VCTarget(**values)


# --------------------------------------------------------------------------- fake HTTP

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeServer:
    """Routes GETs by path; records every request. Handlers return (status, body)."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None, context=None):
        parsed = urlparse(request.full_url)
        self.requests.append((parsed.path, parse_qs(parsed.query), dict(request.header_items())))
        status, body = self.routes[parsed.path](parse_qs(parsed.query), dict(request.header_items()))
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(b"denied"))
        return FakeResponse(json.dumps(body).encode())


class StaticTokens:
    def __init__(self):
        self.refreshes = 0

    def get(self, target, refresh=False):
        self.refreshes += int(refresh)
        return f"tok{self.refreshes}"


def paged(items, key):
    def handler(query, headers):
        offset, limit = int(query["offset"][0]), int(query["limit"][0])
        page = items[offset:offset + limit]
        return 200, {key: page, "meta": {"hasNext": offset + limit < len(items), "count": len(page)}}
    return handler


# --------------------------------------------------------------------------- api

def test_list_all_follows_pagination_and_requests_latest_run():
    jobs = [{"name": f"job-{i}", "type": "spark"} for i in range(250)]
    server = FakeServer({"/dex/api/v1/jobs": paged(jobs, "jobs")})
    api = CdeJobsApi(make_target(), StaticTokens(), ssl_context=None, urlopen=server)

    result = api.jobs()

    assert [j["name"] for j in result] == [j["name"] for j in jobs]
    assert [q["offset"][0] for _, q, _ in server.requests] == ["0", "100", "200"]
    assert all(q["latestjob"] == ["true"] for _, q, _ in server.requests)


def test_list_all_without_meta_reads_a_single_page():
    server = FakeServer({"/dex/api/v1/resources": lambda q, h: (200, {"resources": [{"name": "r"}] * 100})})
    api = CdeJobsApi(make_target(), StaticTokens(), ssl_context=None, urlopen=server)
    assert len(api.resources()) == 100
    assert len(server.requests) == 1


def test_401_refreshes_token_once():
    calls = {"n": 0}

    def handler(query, headers):
        calls["n"] += 1
        return (401, None) if calls["n"] == 1 else (200, {"jobs": [], "meta": {"hasNext": False}})

    tokens = StaticTokens()
    server = FakeServer({"/dex/api/v1/jobs": handler})
    CdeJobsApi(make_target(), tokens, ssl_context=None, urlopen=server).jobs()
    assert tokens.refreshes == 1
    assert server.requests[1][2]["Authorization"] == "Bearer tok1"


# --------------------------------------------------------------------------- auth

def test_token_url_derived_from_vc_api_url_then_fqdn():
    assert auth.token_url(make_target()) == TOKEN_URL
    fqdn_only = make_target(vc_api_url=None)
    assert auth.token_url(fqdn_only) == TOKEN_URL
    assert auth.token_url(make_target(vc_api_url=None, cluster_fqdn=None)) is None


def test_knox_provider_uses_basic_auth_and_caches_per_service():
    seen = []

    def handler(query, headers):
        seen.append(headers["Authorization"])
        return 200, {"access_token": "jwt-1"}

    server = FakeServer({"/gateway/authtkn/knoxtoken/api/v1/token": handler})
    provider = auth.KnoxTokenProvider("wl_user", lambda: "pw", ssl_context=None, urlopen=server)
    assert provider.get(make_target()) == "jwt-1"
    assert provider.get(make_target(vc_name="vc-prod", vc_id="dex-2")) == "jwt-1"  # same service host
    assert len(seen) == 1
    assert seen[0] == "Basic d2xfdXNlcjpwdw=="  # base64("wl_user:pw")


def test_knox_provider_error_hides_credentials():
    server = FakeServer({"/gateway/authtkn/knoxtoken/api/v1/token": lambda q, h: (401, None)})
    provider = auth.KnoxTokenProvider("wl_user", lambda: "s3cret", ssl_context=None, urlopen=server)
    with pytest.raises(auth.AuthError) as exc:
        provider.get(make_target())
    assert exc.value.status == 401
    assert "s3cret" not in str(exc.value)


def test_password_supplier_requires_env_when_not_interactive(monkeypatch):
    monkeypatch.delenv(auth.PASSWORD_ENV, raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO())
    with pytest.raises(auth.AuthError):
        auth.password_from_env_or_prompt("u")()
    monkeypatch.setenv(auth.PASSWORD_ENV, "pw")
    assert auth.password_from_env_or_prompt("u")() == "pw"


# --------------------------------------------------------------------------- rules

def codes(job, target=None, resources=None):
    return [f.code for f in rules.assess(job, target or make_target(), resources)]


@pytest.mark.parametrize("version,expected", [
    ("SPARK2", "SPARK2"), ("2.4.8", "SPARK2"),
    ("SPARK3_2", "SPARK3_REBASE"), ("3.3.0", "SPARK3_REBASE"),
    ("SPARK3", "SPARK3_MINOR_UNKNOWN"), (None, "SPARK_VERSION_UNKNOWN"),
])
def test_spark_version_rules(version, expected):
    assert expected in codes({"type": "spark", "spark": {}}, make_target(spark_version=version))


def test_spark_35_securityhardened_is_low():
    assert codes({"type": "spark", "spark": {"file": "app.jar"}}) == ["NO_BLOCKERS"]


def test_ubi_image_flagged():
    assert "UBI_IMAGE" in codes({"type": "spark"}, make_target(spark_os="ubi"))


def test_default_python_only_for_pyspark_on_spark32():
    target = make_target(spark_version="3.2.3")
    assert "DEFAULT_PYTHON" in codes({"spark": {"file": "etl.py"}}, target)
    assert "DEFAULT_PYTHON" not in codes({"spark": {"file": "etl.jar"}}, target)


def test_legacy_python_env_via_mount():
    resources = {"py38": {"name": "py38", "type": "python-env", "pythonEnv": {"pythonVersion": "python3.8"}}}
    job = {"spark": {"file": "etl.py"}, "mounts": [{"resourceName": "py38"}]}
    assert "PYTHON_ENV_LEGACY" in codes(job, resources=resources)


def test_removed_jvm_flags_detected():
    job = {"spark": {"conf": {
        "spark.driver.extraJavaOptions": "-XX:+UseConcMarkSweepGC -XX:MaxPermSize=512m",
        "spark.executor.extraJavaOptions": "-XX:+UseG1GC",
    }}}
    found = codes(job)
    assert "JVM_FLAG_UseConcMarkSweepGC" in found
    assert "JVM_FLAG_MaxPermSize" in found
    assert "JVM_FLAG_PermSize" not in found


def test_custom_runtime_image_rules():
    spark2 = {"img": {"name": "img", "customRuntimeImage": {"engine": "spark2", "image": "x"}}}
    spark3 = {"img": {"name": "img", "customRuntimeImage": {"engine": "spark3", "image": "x"}}}
    job = {"runtimeImageResourceName": "img", "spark": {}}
    assert "SPARK2_RUNTIME_IMAGE" in codes(job, resources=spark2)
    assert "CUSTOM_RUNTIME_IMAGE" not in codes(job, resources=spark2)
    assert "CUSTOM_RUNTIME_IMAGE" in codes(job, resources=spark3)


def test_airflow_job_skips_spark_rules():
    assert codes({"type": "airflow", "airflow": {"dagFile": "d.py"}}, make_target(spark_version="3.2.3")) == ["AIRFLOW_JOB"]


def test_findings_sorted_most_severe_first():
    found = rules.assess({"spark": {}}, make_target(spark_version="SPARK2", spark_os="ubi"))
    assert [f.severity for f in found] == ["CRITICAL", "MEDIUM"]
    assert rules.max_severity(found) == "CRITICAL"


# --------------------------------------------------------------------------- report

def test_row_redacts_secrets_in_conf_and_args():
    job = {
        "name": "j", "type": "spark",
        "spark": {
            "file": "a.py",
            "conf": {"spark.hadoop.fs.s3a.secret.key": "AKIA-SECRET", "spark.sql.shuffle.partitions": "200",
                     "spark.kerberos.keytab": "/x.keytab"},
            "args": ["--password", "hunter2", "db_pwd=hunter3", "--table", "t1"],
        },
        "latestRunInfo": {"id": 7, "status": "succeeded"},
    }
    row = report.build_row(job, make_target(), {})
    conf = json.loads(row["spark_conf"])
    assert conf["spark.hadoop.fs.s3a.secret.key"] == report.REDACTED
    assert conf["spark.kerberos.keytab"] == report.REDACTED
    assert conf["spark.sql.shuffle.partitions"] == "200"
    assert json.loads(row["args"]) == ["--password", report.REDACTED, f"db_pwd={report.REDACTED}", "--table", "t1"]
    assert "hunter" not in json.dumps(row)
    assert row["last_run_status"] == "succeeded" and row["last_run_id"] == 7
    assert set(row) - {"findings"} == set(report.INVENTORY_COLUMNS)
    assert row["findings"][0]["code"] in row["finding_codes"]


def test_never_run_job():
    assert report.build_row({"name": "j"}, make_target(), {})["last_run_status"] == "never_run"


# --------------------------------------------------------------------------- targets

class StubClient:
    def list_cde_services(self):
        return {"services": [
            {"name": "svc-a", "clusterId": "cluster-a", "environmentName": ENV, "status": "ClusterCreationCompleted"},
            {"name": "gone", "clusterId": "cluster-d", "environmentName": ENV, "status": "ClusterDeletionCompleted"},
            {"name": "other", "clusterId": "cluster-x", "environmentName": "other-env"},
        ]}, None

    def describe_cde_service(self, cluster_id):
        return {"service": {"name": "svc-a", "clusterId": cluster_id, "clusterFqdn": "cde-xyz.example",
                            "version": "1.24.1", "environmentName": ENV}}, None

    def list_cde_virtual_clusters(self, cluster_id):
        return {"vcs": [{"vcId": "dex-1", "vcName": "vc-dev"}, {"vcId": "dex-2", "vcName": "vc-old"}]}, None

    def describe_cde_virtual_cluster(self, cluster_id, vc_id):
        if vc_id == "dex-2":
            return {"vc": {"vcId": vc_id, "vcName": "vc-old", "status": "AppDeleting"}}, None
        return {"vc": {"vcId": vc_id, "vcName": "vc-dev", "status": "AppInstalled", "vcApiUrl": VC_API,
                       "sparkVersion": "SPARK3_3", "sparkOSName": "ubi"}}, None


def test_targets_from_cli_filters_env_and_deleted():
    targets = targets_from_cli(StubClient(), [ENV])
    assert [(t.service_name, t.vc_name) for t in targets] == [("svc-a", "vc-dev"), ("svc-a", "vc-old")]
    dev, old = targets
    assert dev.skip_reason is None and dev.spark_version == "SPARK3_3" and dev.cde_version == "1.24.1"
    assert old.skip_reason  # no vcApiUrl and deleting


def test_targets_from_discovery_dir(tmp_path):
    svc_dir = tmp_path / "discovery_env_test-env-1" / "cde" / "svc-a"
    vc_dir = svc_dir / "virtual_clusters" / "vc-dev"
    vc_dir.mkdir(parents=True)
    (svc_dir / "ENV_test-env_CDE_svc-a_UpgradeStatus_20261105.json").write_text(json.dumps({"neverUpgraded": True}))
    (svc_dir / "ENV_test-env_CDE_svc-a_20261105.json").write_text(json.dumps(
        {"service": {"name": "svc-a", "clusterId": "cluster-a", "environmentName": ENV, "version": "1.25.0"}}))
    (vc_dir / "vc_vc-dev_20261104.json").write_text(json.dumps({"vc": {"vcId": "old"}}))
    (vc_dir / "vc_vc-dev_20261105.json").write_text(json.dumps(
        {"vc": {"vcId": "dex-1", "vcName": "vc-dev", "vcApiUrl": VC_API, "sparkVersion": "SPARK3_5"}}))

    [target] = targets_from_discovery_dir(tmp_path)
    assert (target.environment, target.vc_id, target.cde_version) == (ENV, "dex-1", "1.25.0")


def test_filter_targets_globs():
    targets = [make_target(vc_name=n) for n in ("dev-a", "prod-a", "prod-b")]
    assert [t.vc_name for t in filter_targets(targets, ["prod-*"], ["*-b"])] == ["prod-a"]


# --------------------------------------------------------------------------- end to end

def test_collect_records_failed_vc_and_continues():
    good = make_target()
    bad = make_target(vc_name="vc-bad", vc_api_url="https://bad.cde-xyz.example/dex/api/v1")
    jobs = [{"name": "j1", "type": "spark", "spark": {"file": "a.py"}}]
    server = FakeServer({
        "/dex/api/v1/jobs": lambda q, h: (200, {"jobs": jobs, "meta": {"hasNext": False}}),
        "/dex/api/v1/resources": lambda q, h: (403, None),
    })
    def route(request, timeout=None, context=None):
        if "bad." in request.full_url:
            raise urllib.error.URLError("connection refused")
        return server(request, timeout, context)

    skipped = make_target(vc_name="skip", skip_reason="VC status AppDeleting")
    rows, outcomes = collect([bad, good, skipped], StaticTokens(), None, 5, urlopen=route)

    assert [o["status"] for o in outcomes] == ["failed", "ok", "skipped"]
    assert "resources_error" in outcomes[1]
    assert [r["job_name"] for r in rows] == ["j1"]


def test_collect_aborts_after_rejected_credentials():
    class RejectingTokens:
        def get(self, target, refresh=False):
            raise auth.AuthError("Token request failed: HTTP 401", 401)

    targets = [make_target(vc_name=f"vc-{i}") for i in range(3)]
    rows, outcomes = collect(targets, RejectingTokens(), None, 5)
    assert rows == []
    assert [o["status"] for o in outcomes] == ["failed", "not_attempted", "not_attempted"]


def test_write_reports(tmp_path):
    target = make_target(spark_version="3.2.3")
    rows = [report.build_row({"name": "j", "spark": {"file": "a.py"}}, target, {})]
    outcomes = [{"label": target.label, "status": "ok"}]
    paths = report.write_reports(tmp_path / "out", rows, outcomes, {"tool": "t"})

    with open(paths["inventory_csv"], newline="") as handle:
        [csv_row] = list(csv.DictReader(handle))
    assert csv_row["max_severity"] == "HIGH"
    [summary] = list(csv.DictReader(open(paths["summary_csv"], newline="")))
    assert summary["high"] == "1" and summary["jobs"] == "1"
    assert json.loads(paths["manifest"].read_text())["virtual_clusters"][0]["status"] == "ok"
    assert oct(paths["inventory_csv"].stat().st_mode & 0o777) == "0o600"


def test_cli_dry_run_offline_makes_no_http_calls(tmp_path, capsys, monkeypatch):
    vc_dir = tmp_path / "cde" / "svc-a" / "virtual_clusters" / "vc-dev"
    vc_dir.mkdir(parents=True)
    (tmp_path / "cde" / "svc-a" / "ENV_test-env_CDE_svc-a_1.json").write_text(
        json.dumps({"service": {"name": "svc-a", "clusterId": "c", "environmentName": ENV}}))
    (vc_dir / "vc_vc-dev_1.json").write_text(json.dumps({"vc": {"vcId": "dex-1", "vcName": "vc-dev", "vcApiUrl": VC_API}}))

    def no_network(*a, **k):
        raise AssertionError("network call in dry run")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    assert main(["--discovery-dir", str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert TOKEN_URL in out and "test-env/svc-a/vc-dev" in out
