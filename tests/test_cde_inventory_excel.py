"""Executive Excel report: data shaping (no openpyxl needed) and workbook rendering (needs openpyxl)."""

import json

import pytest

from cdp_discover.cde_inventory import excel_report, report, report_cli
from cdp_discover.cde_inventory.targets import VCTarget


def target(env="env-a", vc="vc-1", spark="3.5.4"):
    return VCTarget(environment=env, service_name="svc", cluster_id="c", vc_name=vc, vc_id=vc,
                    vc_api_url=f"https://{vc}.cde-x.example/dex/api/v1", vc_status="AppInstalled",
                    spark_version=spark, spark_os="securityhardened")


def write_inventory(directory, rows, targets):
    outcomes = [{"label": t.label, **t.to_dict(), "status": "ok", "jobs": 1} for t in targets]
    report.write_reports(directory, rows, outcomes, {"tool": "t", "toolVersion": "0.3.0",
                                                     "finishedAt": "2026-11-05T20:32:38+00:00"})
    return directory


@pytest.fixture
def two_envs(tmp_path):
    t_old, t_new = target("env-a", "vc-old", "SPARK2"), target("env-b", "vc-new", "3.5.4")
    dir_a = write_inventory(tmp_path / "a", [
        report.build_row({"name": "legacy", "spark": {"file": "a.py"}}, t_old, {}),
        report.build_row({"name": "jvm", "spark": {"file": "b.jar", "conf": {
            "spark.driver.extraJavaOptions": "-XX:+UseConcMarkSweepGC"}}}, t_old, {}),
    ], [t_old])
    dir_b = write_inventory(tmp_path / "b", [
        report.build_row({"name": "ok-1", "spark": {"file": "c.py"}}, t_new, {}),
        report.build_row({"name": "ok-2", "spark": {"file": "d.py"}}, t_new, {}),
    ], [t_new])
    return dir_a, dir_b


def test_load_merges_dirs_and_computes_kpis(two_envs):
    bundle = excel_report.load_inventory(two_envs)
    kpis = excel_report.compute_kpis(bundle)
    assert kpis["environments"] == ["env-a", "env-b"]
    assert (kpis["vcs"], kpis["vcs_ok"], kpis["jobs"]) == (2, 2, 4)
    assert kpis["by_severity"]["CRITICAL"] == 2 and kpis["by_severity"]["LOW"] == 2
    assert kpis["blocking"] == 2 and kpis["readiness_pct"] == 50.0


def test_headlines_call_out_blockers(two_envs):
    bundle = excel_report.load_inventory(two_envs)
    text = " ".join(excel_report.headlines(bundle, excel_report.compute_kpis(bundle)))
    assert "2 job(s) will fail" in text and "50.0% of jobs (2 of 4)" in text


def test_remediation_rollup(two_envs):
    rows = excel_report.load_inventory(two_envs).rows
    plan = {r["code"]: r for r in excel_report._remediation_rows(rows)}
    assert plan["SPARK2"]["jobs"] == 2 and plan["SPARK2"]["vcs"] == 1
    assert plan["JVM_FLAG_UseConcMarkSweepGC"]["action"].startswith("Remove JDK 17")
    assert list(plan)[0] == "SPARK2"  # most severe first
    assert all(f["code"] != "NO_BLOCKERS" for f in excel_report._finding_rows(rows))


def test_findings_fallback_for_old_inventories():
    row = {"max_severity": "CRITICAL", "finding_codes": "SPARK2,UBI_IMAGE",
           "upgrade_732_impact_assessment": "CRITICAL: VC runs Spark 2; Spark 2 is removed. Migrate.; MEDIUM: ubi; move."}
    assert [(f["severity"], f["code"]) for f in excel_report.findings_of(row)] == [
        ("CRITICAL", "SPARK2"), ("MEDIUM", "UBI_IMAGE")]
    low = {"finding_codes": "NO_BLOCKERS",
           "upgrade_732_impact_assessment": "LOW: No breaking configuration detected; ready for 7.3.2 testing."}
    assert excel_report.findings_of(low)[0]["message"].endswith("testing.")


def test_missing_inventory_dir_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        excel_report.load_inventory([tmp_path])


def test_report_cli_without_openpyxl(monkeypatch, tmp_path):
    monkeypatch.setattr(report_cli, "openpyxl_available", lambda: False)
    assert report_cli.main(["--inventory-dir", str(tmp_path)]) == 2


# --------------------------------------------------------------------------- workbook (openpyxl)

def test_workbook_sheets_kpis_and_colors(two_envs, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = report_cli.generate(list(two_envs), tmp_path / "exec.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["EXECUTIVE SUMMARY", "Virtual Clusters", "Job Inventory", "Findings",
                             "Remediation Plan", "Run Details", "CLI Analysis"]

    summary = {ws_row[0]: ws_row[1] for ws_row in wb["EXECUTIVE SUMMARY"].iter_rows(values_only=True) if ws_row[0]}
    assert summary["Jobs inventoried"] == 4
    assert summary["Readiness (jobs with no blockers)"] == 0.5
    assert summary["Environments"] == "env-a, env-b"

    jobs = wb["Job Inventory"]
    assert jobs.max_row == 2 + 4  # banner + header + 4 jobs
    header = [c.value for c in jobs[2]]
    sev_cell = jobs.cell(row=3, column=header.index("Worst Severity") + 1)
    assert sev_cell.value == "CRITICAL"  # sorted most severe first
    assert sev_cell.fill.fgColor.rgb.endswith("C00000")
    assert wb["CLI Analysis"].max_row == 2 + len(excel_report.CLI_RECIPES)
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_default_output_name(two_envs):
    pytest.importorskip("openpyxl")
    single = report_cli.generate([two_envs[1]])
    assert single.name == "CDE_UpgradeImpact_env-b.xlsx" and single.parent == two_envs[1]
    merged = report_cli.generate(list(two_envs))
    assert merged.name == "CDE_UpgradeImpact_multi-env.xlsx"


def test_inventory_cli_skips_excel_cleanly_without_openpyxl(monkeypatch, tmp_path):
    from cdp_discover.cde_inventory import cli

    monkeypatch.setattr(report_cli, "openpyxl_available", lambda: False)
    assert cli._write_excel(tmp_path) is None
    # the JSON row keeps structured findings for jq / the workbook
    row = report.build_row({"name": "j", "spark": {}}, target(spark="SPARK2"), {})
    assert json.loads(json.dumps(row))["findings"][0]["code"] == "SPARK2"
