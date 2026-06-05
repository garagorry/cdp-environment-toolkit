"""builders — turn a DiscoveryBundle into per-sheet rows.

Each builder returns a list of "record" dicts. The Excel writer applies the
column accessors from ``columns_aws`` to each record. Records are flat enough
that the same accessor path works for every row of a given sheet.

The builders explode arrays so that:

* FREEIPA rows = (env, instance) pairs
* DATALAKE rows = (env, datalake, group, instance) tuples
* DATAHUBS rows = (env, cluster, group, instance) tuples
* CDW rows = one per CDW cluster
* CMLCAI rows = one per ML workspace (+ LatestVersion / Backups / Access sidecars)
* CAI_INSTANCES / CAI_SERVING / CAI_REGISTRY from CAI sidecar JSON trees
* CDW rows = one per CDW cluster; CDW_DBC / CDW_VW / CDW_DVIZ / CDW_HUE from sidecars
* CDE rows = one per (service, virtual cluster); service-only row if no VCs
* CDF rows = one per (service, deployment); service-only row if no deployments
* COD rows = one per (database, instance group, instance); instance groups
  from ``*_DataHub_*.json`` when ``databaseDetails`` has no ``instanceGroups``
* DATABASES rows = one per redbeams DB JSON
* DATALAKE_HEALTH rows = one per (datalake, CM service) from ``*_ServiceStatus_*.json``
* DATALAKE_HOSTS rows = one per host from ``*_HostStatus_*.json``
* DATAHUB_HEALTH rows = one per (cluster, CM service) from ``*_ServiceStatus_*.json``
* DATAHUB_HOSTS rows = one per host from ``*_HostStatus_*.json``
* DATAHUB_AUTOSCALE_HISTORY rows = one per autoscale event from ``*_AutoScaleHistory_*.json``
* DATAHUB_LIFECYCLE rows = one per lifecycle event from ``*_LifecycleEvents_*.json``
* CDF_DEPLOYMENT_EVENTS / CDF_DEPLOYMENT_ALERTS from deployment sidecars
"""
from __future__ import annotations

import os
from glob import glob
from typing import Dict, List

from .common import at, load_json
from .loader import DiscoveryBundle


def _load_sidecar_json(folder: str, marker: str) -> dict:
    """First JSON under ``folder`` whose basename contains ``_<marker>_``."""
    for path in sorted(glob(os.path.join(folder, f"*_{marker}_*.json"))):
        doc = load_json(path)
        if doc:
            return doc
    return {}


def _service_health_rows(
    env: dict,
    resource_key: str,
    resource_obj: dict,
    status_doc: dict,
) -> List[dict]:
    services = status_doc.get("services") or []
    if not services:
        return [{"environment": env, resource_key: resource_obj, "service": {}}]
    return [
        {"environment": env, resource_key: resource_obj, "service": svc}
        for svc in services
    ]


def _host_status_rows(
    env: dict,
    resource_key: str,
    resource_obj: dict,
    host_doc: dict,
) -> List[dict]:
    hosts = host_doc.get("hosts") or []
    if not hosts:
        return [{"environment": env, resource_key: resource_obj, "host": {}}]
    return [
        {"environment": env, resource_key: resource_obj, "host": host}
        for host in hosts
    ]


def build_environment(bundle: DiscoveryBundle) -> List[dict]:
    if not bundle.environment:
        return []
    return [bundle.environment]


def build_freeipa(bundle: DiscoveryBundle) -> List[dict]:
    if not bundle.environment:
        return []
    instances = at("environment.freeipa.instances")(bundle.environment) or []
    if not instances:
        return [{"environment": bundle.environment["environment"], "instance": {}}]
    return [
        {"environment": bundle.environment["environment"], "instance": inst}
        for inst in instances
    ]


def build_datalake(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for dl in bundle.datalakes:
        datalake = dl.main_json.get("datalake", {})
        groups = datalake.get("instanceGroups") or []
        if not groups:
            rows.append({"environment": env, "datalake": datalake, "group": {}, "instance": {}})
            continue
        for group in groups:
            instances = group.get("instances") or []
            if not instances:
                rows.append({
                    "environment": env, "datalake": datalake,
                    "group": group, "instance": {},
                })
                continue
            for inst in instances:
                rows.append({
                    "environment": env, "datalake": datalake,
                    "group": group, "instance": inst,
                })
    return rows


def build_datalake_health(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for dl in bundle.datalakes:
        datalake = dl.main_json.get("datalake", {})
        status_doc = _load_sidecar_json(dl.folder, "ServiceStatus")
        rows.extend(_service_health_rows(env, "datalake", datalake, status_doc))
    return rows


def build_datalake_hosts(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for dl in bundle.datalakes:
        datalake = dl.main_json.get("datalake", {})
        host_doc = _load_sidecar_json(dl.folder, "HostStatus")
        rows.extend(_host_status_rows(env, "datalake", datalake, host_doc))
    return rows


def build_datahubs(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        groups = cluster.get("instanceGroups") or []
        if not groups:
            rows.append({
                "environment": env, "datalake": primary_dl,
                "cluster": cluster, "group": {}, "instance": {},
            })
            continue
        for group in groups:
            instances = group.get("instances") or []
            if not instances:
                rows.append({
                    "environment": env, "datalake": primary_dl,
                    "cluster": cluster, "group": group, "instance": {},
                })
                continue
            for inst in instances:
                rows.append({
                    "environment": env, "datalake": primary_dl,
                    "cluster": cluster, "group": group, "instance": inst,
                })
    return rows


def build_datahub_health(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        status_doc = _load_sidecar_json(dh.folder, "ServiceStatus")
        for row in _service_health_rows(env, "cluster", cluster, status_doc):
            row["datalake"] = primary_dl
            rows.append(row)
    return rows


def build_datahub_hosts(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        host_doc = _load_sidecar_json(dh.folder, "HostStatus")
        for row in _host_status_rows(env, "cluster", cluster, host_doc):
            row["datalake"] = primary_dl
            rows.append(row)
    return rows


def build_datahub_autoscale_history(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        history_doc = _load_sidecar_json(dh.folder, "AutoScaleHistory")
        events = history_doc.get("historyEvents") or []
        if not events:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "event": {},
            })
            continue
        for event in events:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "event": event,
            })
    return rows


def _lifecycle_sort_key(record: dict) -> str:
    ts = (record.get("event") or {}).get("eventTimestamp")
    return str(ts) if ts is not None else ""


def build_datahub_lifecycle(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        events_doc = _load_sidecar_json(dh.folder, "LifecycleEvents")
        events = events_doc.get("clusterEvents") or []
        if not events:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "event": {},
            })
            continue
        for event in events:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "event": event,
            })
    rows.sort(key=_lifecycle_sort_key, reverse=True)
    return rows


def build_databases(bundle: DiscoveryBundle) -> List[dict]:
    return list(bundle.databases)


def _cai_workspace_doc(main_json: dict) -> dict:
    return main_json.get("workspace") or main_json


def build_cmlcai(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cai in bundle.cais:
        rows.append({
            "workspace": _cai_workspace_doc(cai.main_json),
            "latestVersion": _load_sidecar_json(cai.folder, "LatestVersion"),
            "backups": _load_sidecar_json(cai.folder, "Backups"),
            "access": _load_sidecar_json(cai.folder, "Access"),
        })
    return rows


def build_cai_instances(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cai in bundle.cais:
        workspace = _cai_workspace_doc(cai.main_json)
        groups = workspace.get("instanceGroups") or []
        if not groups:
            rows.append({"workspace": workspace, "group": {}, "instance": {}})
            continue
        for group in groups:
            instances = group.get("instances") or []
            if not instances:
                rows.append({"workspace": workspace, "group": group, "instance": {}})
                continue
            for inst in instances:
                rows.append({"workspace": workspace, "group": group, "instance": inst})
    return rows


def _load_json_resources_in_subdirs(
    parent_dir: str,
    file_glob: str,
    resource_keys: tuple,
    skip_substrings: tuple = (),
) -> List[dict]:
    """Load described resources from ``parent/<name>/*.json``."""
    if not os.path.isdir(parent_dir):
        return []
    out: List[dict] = []
    for entry in sorted(os.listdir(parent_dir)):
        sub = os.path.join(parent_dir, entry)
        if not os.path.isdir(sub):
            continue
        for path in sorted(glob(os.path.join(sub, file_glob))):
            base = os.path.basename(path)
            if any(s in base for s in skip_substrings):
                continue
            doc = load_json(path)
            if not doc:
                continue
            obj = None
            for key in resource_keys:
                if isinstance(doc.get(key), dict):
                    obj = doc[key]
                    break
            if obj is None and isinstance(doc, dict) and doc:
                obj = doc
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _load_cai_account_level_list(cai_root: str, list_glob: str, list_key: str) -> List[dict]:
    for path in sorted(glob(os.path.join(cai_root, list_glob))):
        doc = load_json(path)
        if doc and isinstance(doc.get(list_key), list):
            return [x for x in doc[list_key] if isinstance(x, dict)]
    return []


def build_cai_serving(bundle: DiscoveryBundle) -> List[dict]:
    cai_root = os.path.join(bundle.root, "cai")
    apps = _load_json_resources_in_subdirs(
        os.path.join(cai_root, "ml_serving_apps"),
        "serving_app_*.json",
        ("mlServingApp", "app"),
    )
    if not apps:
        for search_dir in (os.path.join(cai_root, "ml_serving_apps"), cai_root):
            apps = _load_cai_account_level_list(
                search_dir, "ml_serving_apps_list_*.json", "mlServingApps"
            )
            if apps:
                break
    if not apps:
        return [{"app": {}}]
    return [{"app": app} for app in apps]


def build_cai_registry(bundle: DiscoveryBundle) -> List[dict]:
    cai_root = os.path.join(bundle.root, "cai")
    reg_parent = os.path.join(cai_root, "model_registries")
    rows: List[dict] = []
    if os.path.isdir(reg_parent):
        for entry in sorted(os.listdir(reg_parent)):
            sub = os.path.join(reg_parent, entry)
            if not os.path.isdir(sub):
                continue
            reg_doc = {}
            version_doc = {}
            for path in sorted(glob(os.path.join(sub, "model_registry_*.json"))):
                base = os.path.basename(path)
                doc = load_json(path)
                if not doc:
                    continue
                if "LatestVersion" in base:
                    version_doc = doc
                else:
                    reg_doc = doc
            registry = None
            if reg_doc:
                registry = reg_doc.get("modelRegistry") or reg_doc
            if isinstance(registry, dict):
                rows.append({"registry": registry, "latestVersion": version_doc})
    if not rows:
        for reg in _load_cai_account_level_list(
            cai_root, "model_registries_*.json", "modelRegistries"
        ):
            rows.append({"registry": reg, "latestVersion": {}})
    if not rows:
        return [{"registry": {}, "latestVersion": {}}]
    return rows


def _cdw_cluster_doc(main_json: dict) -> dict:
    return main_json.get("cluster") or main_json


def build_cdw(bundle: DiscoveryBundle) -> List[dict]:
    return [c.main_json for c in bundle.cdws]


def _load_cdw_upgrade_json(folder: str, prefix: str) -> dict:
    for path in sorted(glob(os.path.join(folder, f"{prefix}*UpgradeVersions_*.json"))):
        doc = load_json(path)
        if doc:
            return doc
    return {}


def build_cdw_dbc(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdw in bundle.cdws:
        cluster = _cdw_cluster_doc(cdw.main_json)
        dbcs_dir = os.path.join(cdw.folder, "database_catalogs")
        if not os.path.isdir(dbcs_dir):
            rows.append({"cluster": cluster, "dbc": {}, "upgrade": {}})
            continue
        found = False
        for entry in sorted(os.listdir(dbcs_dir)):
            sub = os.path.join(dbcs_dir, entry)
            if not os.path.isdir(sub):
                continue
            for path in sorted(glob(os.path.join(sub, "dbc_*.json"))):
                if "UpgradeVersions" in os.path.basename(path):
                    continue
                doc = load_json(path)
                if not doc:
                    continue
                dbc = doc.get("dbc") or doc
                upgrade = _load_cdw_upgrade_json(sub, f"dbc_{entry}_")
                rows.append({"cluster": cluster, "dbc": dbc, "upgrade": upgrade})
                found = True
        if not found:
            rows.append({"cluster": cluster, "dbc": {}, "upgrade": {}})
    return rows


def build_cdw_vw(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdw in bundle.cdws:
        cluster = _cdw_cluster_doc(cdw.main_json)
        vws_dir = os.path.join(cdw.folder, "virtual_warehouses")
        if not os.path.isdir(vws_dir):
            rows.append({"cluster": cluster, "vw": {}, "upgrade": {}})
            continue
        found = False
        for entry in sorted(os.listdir(vws_dir)):
            sub = os.path.join(vws_dir, entry)
            if not os.path.isdir(sub):
                continue
            for path in sorted(glob(os.path.join(sub, "vw_*.json"))):
                if "UpgradeVersions" in os.path.basename(path):
                    continue
                doc = load_json(path)
                if not doc:
                    continue
                vw = doc.get("vw") or doc
                upgrade = _load_cdw_upgrade_json(sub, f"vw_{entry}_")
                rows.append({"cluster": cluster, "vw": vw, "upgrade": upgrade})
                found = True
        if not found:
            rows.append({"cluster": cluster, "vw": {}, "upgrade": {}})
    return rows


def _load_cdw_data_visualizations(cdw_folder: str) -> List[dict]:
    dvizs: List[dict] = []
    dviz_root = os.path.join(cdw_folder, "data_visualizations")
    if os.path.isdir(dviz_root):
        for entry in sorted(os.listdir(dviz_root)):
            sub = os.path.join(dviz_root, entry)
            if not os.path.isdir(sub):
                continue
            for path in sorted(glob(os.path.join(sub, "dviz_*.json"))):
                doc = load_json(path)
                if not doc:
                    continue
                obj = doc.get("dataVisualization") or doc.get("dataVisualizationDetails") or doc
                if isinstance(obj, dict):
                    dvizs.append(obj)
    for path in sorted(glob(os.path.join(cdw_folder, "data_visualizations_*.json"))):
        doc = load_json(path)
        if not doc:
            continue
        for item in doc.get("dataVisualizations") or []:
            if isinstance(item, dict):
                dvizs.append(item)
    if os.path.isdir(dviz_root):
        for path in sorted(glob(os.path.join(dviz_root, "data_visualizations_list_*.json"))):
            doc = load_json(path)
            for item in doc.get("dataVisualizations") or []:
                if isinstance(item, dict) and item not in dvizs:
                    dvizs.append(item)
    return dvizs


def build_cdw_dviz(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdw in bundle.cdws:
        cluster = _cdw_cluster_doc(cdw.main_json)
        dvizs = _load_cdw_data_visualizations(cdw.folder)
        if not dvizs:
            rows.append({"cluster": cluster, "dviz": {}})
            continue
        for dviz in dvizs:
            rows.append({"cluster": cluster, "dviz": dviz})
    return rows


def build_cdw_hue(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdw in bundle.cdws:
        cluster = _cdw_cluster_doc(cdw.main_json)
        hues: List[dict] = []
        for path in sorted(glob(os.path.join(cdw.folder, "hue_instances_*.json"))):
            doc = load_json(path)
            if doc:
                hues.extend(doc.get("hues") or [])
        if not hues:
            rows.append({"cluster": cluster, "hue": {}})
            continue
        for hue in hues:
            rows.append({"cluster": cluster, "hue": hue})
    return rows


def _load_described_from_tree(
    parent_dir: str,
    file_glob: str,
    resource_keys: tuple,
    skip_substrings: tuple = (),
) -> List[dict]:
    """Load described resources from ``parent/<name>/<file_glob>``."""
    if not os.path.isdir(parent_dir):
        return []
    out: List[dict] = []
    for entry in sorted(os.listdir(parent_dir)):
        sub = os.path.join(parent_dir, entry)
        if not os.path.isdir(sub):
            continue
        for path in sorted(glob(os.path.join(sub, file_glob))):
            base = os.path.basename(path)
            if any(s in base for s in skip_substrings):
                continue
            doc = load_json(path)
            if not doc:
                continue
            obj = None
            for key in resource_keys:
                if isinstance(doc.get(key), dict):
                    obj = doc[key]
                    break
            if obj is None and isinstance(doc, dict) and doc:
                obj = doc
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _load_list_json(folder: str, list_glob: str, list_key: str) -> List[dict]:
    for path in sorted(glob(os.path.join(folder, list_glob))):
        doc = load_json(path)
        if doc and isinstance(doc.get(list_key), list):
            return [x for x in doc[list_key] if isinstance(x, dict)]
    return []


def _cde_service_doc(main_json: dict) -> dict:
    return main_json.get("service") or main_json


def _load_cde_virtual_clusters(service_folder: str) -> List[dict]:
    """Return VC dicts from ``cde/<service>/virtual_clusters/*/vc_*.json``."""
    vc_root = os.path.join(service_folder, "virtual_clusters")
    vcs = _load_described_from_tree(vc_root, "vc_*.json", ("vc",))
    if vcs:
        return vcs
    return _load_list_json(vc_root, "virtual_clusters_list_*.json", "vcs")


def _load_cde_upgrade_status(service_folder: str) -> dict:
    return _load_sidecar_json(service_folder, "UpgradeStatus")


def _load_cde_backups(service_folder: str) -> List[dict]:
    doc = _load_sidecar_json(service_folder, "Backups")
    return doc.get("backups") or []


def build_cde(bundle: DiscoveryBundle) -> List[dict]:
    """One row per CDE service with upgrade sidecar."""
    rows: List[dict] = []
    for cde in bundle.cdes:
        service = _cde_service_doc(cde.main_json)
        rows.append({
            "service": service,
            "upgrade": _load_cde_upgrade_status(cde.folder),
        })
    if not rows:
        return [{"service": {}, "upgrade": {}}]
    return rows


def build_cde_vc(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cde in bundle.cdes:
        service = _cde_service_doc(cde.main_json)
        upgrade = _load_cde_upgrade_status(cde.folder)
        vcs = _load_cde_virtual_clusters(cde.folder)
        if not vcs:
            rows.append({"service": service, "vc": {}, "upgrade": upgrade})
            continue
        for vc in vcs:
            rows.append({"service": service, "vc": vc, "upgrade": upgrade})
    return rows


def build_cde_backups(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cde in bundle.cdes:
        service = _cde_service_doc(cde.main_json)
        backups = _load_cde_backups(cde.folder)
        if not backups:
            rows.append({"service": service, "backup": {}})
            continue
        for backup in backups:
            rows.append({"service": service, "backup": backup})
    return rows


def _cdf_service_doc(main_json: dict) -> dict:
    return main_json.get("service") or main_json


def _load_cdf_deployments(service_folder: str) -> List[dict]:
    deployments_root = os.path.join(service_folder, "deployments")
    deployments = _load_described_from_tree(
        deployments_root, "deployment_*.json", ("deployment",)
    )
    if deployments:
        return deployments
    return _load_list_json(deployments_root, "deployments_list_*.json", "deployments")


def _load_cdf_deployment_sidecar_rows(
    service_folder: str,
    marker: str,
    list_key: str,
) -> List[dict]:
    """Load per-deployment sidecar JSON (events/alerts) with deployment context."""
    rows: List[dict] = []
    deployments_root = os.path.join(service_folder, "deployments")
    if not os.path.isdir(deployments_root):
        return rows
    for entry in sorted(os.listdir(deployments_root)):
        sub = os.path.join(deployments_root, entry)
        if not os.path.isdir(sub):
            continue
        deployment = {}
        for path in sorted(glob(os.path.join(sub, "deployment_*.json"))):
            base = os.path.basename(path)
            if marker in base:
                continue
            doc = load_json(path)
            if doc:
                deployment = doc.get("deployment") or doc
                break
        for path in sorted(glob(os.path.join(sub, f"*_{marker}_*.json"))):
            doc = load_json(path)
            if not doc:
                continue
            items = doc.get(list_key) or []
            if not items:
                rows.append({"deployment": deployment, "item": {}})
                continue
            for item in items:
                rows.append({"deployment": deployment, "item": item})
    return rows


def _cdf_env_name(bundle: DiscoveryBundle) -> str:
    return (bundle.environment or {}).get("environment", {}).get("environmentName") or ""


def _cdf_project_matches_env(project: dict, env_name: str) -> bool:
    if not env_name:
        return True
    svc = project.get("service") or {}
    if svc.get("name") == env_name:
        return True
    env_crn = svc.get("environmentCrn") or ""
    return env_name in env_crn


def build_cdf(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdf in bundle.cdfs:
        service = _cdf_service_doc(cdf.main_json)
        deployments = _load_cdf_deployments(cdf.folder)
        if not deployments:
            rows.append({"service": service, "deployment": {}})
            continue
        for deployment in deployments:
            rows.append({"service": service, "deployment": deployment})
    return rows


def build_cdf_flows(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdf in bundle.cdfs:
        service = _cdf_service_doc(cdf.main_json)
        flows_dir = os.path.join(cdf.folder, "flow_definitions")
        flows = _load_described_from_tree(
            flows_dir,
            "flow_*.json",
            ("flow", "flowDefinition"),
        )
        if not flows:
            flows = _load_list_json(flows_dir, "flows_list_*.json", "flowDefinitions")
        if not flows:
            rows.append({"service": service, "flow": {}})
            continue
        for flow in flows:
            rows.append({"service": service, "flow": flow})
    return rows


def build_cdf_projects(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env_name = _cdf_env_name(bundle)
    seen_crns: set = set()
    for cdf in bundle.cdfs:
        service = _cdf_service_doc(cdf.main_json)
        projects_dir = os.path.join(cdf.folder, "projects")
        projects = _load_described_from_tree(projects_dir, "project_*.json", ("project",))
        if not projects:
            projects = _load_list_json(projects_dir, "projects_list_*.json", "projects")
        for project in projects:
            crn = project.get("crn")
            if crn and crn in seen_crns:
                continue
            if not _cdf_project_matches_env(project, env_name):
                continue
            if crn:
                seen_crns.add(crn)
            rows.append({"service": service, "project": project})
    cdf_root = os.path.join(bundle.root, "cdf")
    for project in _load_list_json(cdf_root, "projects_*.json", "projects"):
        crn = project.get("crn")
        if crn and crn in seen_crns:
            continue
        if not _cdf_project_matches_env(project, env_name):
            continue
        if crn:
            seen_crns.add(crn)
        svc = project.get("service") or {}
        rows.append({"service": svc, "project": project})
    if not rows:
        return [{"service": {}, "project": {}}]
    return rows


def build_cdf_readyflows(bundle: DiscoveryBundle) -> List[dict]:
    cdf_root = os.path.join(bundle.root, "cdf")
    readyflows_dir = os.path.join(cdf_root, "readyflows")
    readyflows = _load_described_from_tree(
        readyflows_dir,
        "readyflow_*.json",
        ("readyflow", "readyFlow"),
    )
    if not readyflows:
        readyflows = _load_list_json(cdf_root, "readyflows_*.json", "readyflows")
    if not readyflows:
        readyflows = _load_list_json(readyflows_dir, "readyflows_list_*.json", "readyflows")
    if not readyflows:
        return [{"readyflow": {}}]
    return [{"readyflow": rf} for rf in readyflows]


def build_cdf_deployment_events(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdf in bundle.cdfs:
        rows.extend(
            _load_cdf_deployment_sidecar_rows(
                cdf.folder, "DeploymentEvents", "eventSummaries"
            )
        )
    if not rows:
        return [{"deployment": {}, "item": {}}]
    return rows


def build_cdf_deployment_alerts(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    for cdf in bundle.cdfs:
        rows.extend(
            _load_cdf_deployment_sidecar_rows(
                cdf.folder, "DeploymentAlerts", "eventSummaries"
            )
        )
    if not rows:
        return [{"deployment": {}, "item": {}}]
    return rows


def _load_cai_access_rows(parent_dir: str, access_glob: str) -> List[dict]:
    rows: List[dict] = []
    if not os.path.isdir(parent_dir):
        return rows
    for entry in sorted(os.listdir(parent_dir)):
        sub = os.path.join(parent_dir, entry)
        if not os.path.isdir(sub):
            continue
        resource = {}
        for path in sorted(glob(os.path.join(sub, "*.json"))):
            base = os.path.basename(path)
            if "_Access_" in base:
                continue
            doc = load_json(path)
            if not doc:
                continue
            for key in ("mlServingApp", "app", "modelRegistry", "registry"):
                if isinstance(doc.get(key), dict):
                    resource = doc[key]
                    break
            if not resource and isinstance(doc, dict):
                resource = doc
            break
        for path in sorted(glob(os.path.join(sub, access_glob))):
            doc = load_json(path)
            if not doc:
                continue
            access_list = doc.get("access") or []
            if not access_list:
                rows.append({"resource": resource, "access": {}})
                continue
            for access in access_list:
                rows.append({"resource": resource, "access": access})
    return rows


def build_cai_serving_access(bundle: DiscoveryBundle) -> List[dict]:
    cai_root = os.path.join(bundle.root, "cai")
    rows = _load_cai_access_rows(
        os.path.join(cai_root, "ml_serving_apps"),
        "serving_app_*_Access_*.json",
    )
    if not rows:
        return [{"resource": {}, "access": {}}]
    return rows


def build_cai_registry_access(bundle: DiscoveryBundle) -> List[dict]:
    cai_root = os.path.join(bundle.root, "cai")
    rows = _load_cai_access_rows(
        os.path.join(cai_root, "model_registries"),
        "model_registry_*_Access_*.json",
    )
    if not rows:
        return [{"resource": {}, "access": {}}]
    return rows


def _cod_database_doc(main_json: dict) -> dict:
    return main_json.get("databaseDetails") or main_json.get("database") or main_json


def _load_datahub_cluster_by_name(bundle: DiscoveryBundle, cluster_name: str) -> dict:
    """Resolve backing DataHub cluster from bundle assets or ``datahub/<name>/``."""
    if not cluster_name:
        return {}
    for dh in bundle.datahubs:
        if dh.name == cluster_name:
            cluster = dh.main_json.get("cluster")
            if isinstance(cluster, dict):
                return cluster
    dh_folder = os.path.join(bundle.root, "datahub", cluster_name)
    if not os.path.isdir(dh_folder):
        return {}
    skip = (
        "_AvailableImages_", "_RunTimeAvailableImages_", "_Template_", "_DB_",
        "_ServiceStatus_", "_LifecycleEvents_", "_InstanceGroups_",
    )
    for path in sorted(glob(os.path.join(dh_folder, f"*_{cluster_name}_*.json"))):
        base = os.path.basename(path)
        if "_DH_" not in base or any(s in base for s in skip):
            continue
        doc = load_json(path)
        if doc and isinstance(doc.get("cluster"), dict):
            return doc["cluster"]
    return {}


def _load_cod_backing_datahub(cod_folder: str, bundle: DiscoveryBundle, internal_name: str) -> dict:
    """Cluster from COD sidecar, else ``datahub/<internalName>/`` main describe JSON."""
    for path in sorted(glob(os.path.join(cod_folder, "*_DataHub_*.json"))):
        if "InstanceGroups" in os.path.basename(path):
            continue
        doc = load_json(path)
        if doc and isinstance(doc.get("cluster"), dict):
            return doc["cluster"]
    return _load_datahub_cluster_by_name(bundle, internal_name)


def _cod_instance_groups(database: dict, cod_folder: str, bundle: DiscoveryBundle):
    groups = database.get("instanceGroups") or []
    if groups:
        return groups, {}
    internal_name = database.get("internalName") or ""
    cluster = _load_cod_backing_datahub(cod_folder, bundle, internal_name)
    return cluster.get("instanceGroups") or [], cluster


def _load_datahub_sidecar(bundle: DiscoveryBundle, cluster_name: str, marker: str) -> dict:
    if not cluster_name:
        return {}
    folder = os.path.join(bundle.root, "datahub", cluster_name)
    return _load_sidecar_json(folder, marker)


def build_cod(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for cod in bundle.cods:
        database = _cod_database_doc(cod.main_json)
        groups, cluster = _cod_instance_groups(database, cod.folder, bundle)
        if not groups:
            rows.append({
                "environment": env,
                "database": database,
                "cluster": cluster,
                "group": {},
                "instance": {},
            })
            continue
        for group in groups:
            instances = group.get("instances") or []
            if not instances:
                rows.append({
                    "environment": env,
                    "database": database,
                    "cluster": cluster,
                    "group": group,
                    "instance": {},
                })
                continue
            for inst in instances:
                rows.append({
                    "environment": env,
                    "database": database,
                    "cluster": cluster,
                    "group": group,
                    "instance": inst,
                })
    return rows


def build_cod_opdb(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for cod in bundle.cods:
        database = _cod_database_doc(cod.main_json)
        snapshots_doc = _load_sidecar_json(cod.folder, "Snapshots")
        restore_doc = _load_sidecar_json(cod.folder, "RestoreSnapshots")
        diagnostics_doc = _load_sidecar_json(cod.folder, "Diagnostics")
        rows.append({
            "environment": env,
            "database": database,
            "upgrade": _load_sidecar_json(cod.folder, "Upgrade"),
            "connectivity": _load_sidecar_json(cod.folder, "ClientConnectivity"),
            "snapshots": snapshots_doc,
            "snapshotCount": len(snapshots_doc.get("snapshots") or []),
            "restoreSnapshots": restore_doc,
            "restoreSnapshotCount": len(restore_doc.get("snapshots") or restore_doc.get("restoreSnapshots") or []),
            "diagnostics": diagnostics_doc,
            "diagnosticsCount": len(diagnostics_doc.get("diagnostics") or []),
        })
    return rows


def build_cod_datahub_health(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for cod in bundle.cods:
        database = _cod_database_doc(cod.main_json)
        internal_name = database.get("internalName") or ""
        cluster = _load_cod_backing_datahub(cod.folder, bundle, internal_name)
        status_doc = _load_datahub_sidecar(bundle, internal_name, "ServiceStatus")
        for row in _service_health_rows(env, "cluster", cluster, status_doc):
            row["database"] = database
            rows.append(row)
    return rows


def _load_latest_service_list(
    root: str,
    service_dir: str,
    file_glob: str,
    list_keys: tuple,
) -> List[dict]:
    parent = os.path.join(root, service_dir)
    if not os.path.isdir(parent):
        return []
    for path in sorted(glob(os.path.join(parent, file_glob)), reverse=True):
        doc = load_json(path)
        if not doc:
            continue
        for key in list_keys:
            items = doc.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def _rows_from_list(items: List[dict], item_key: str) -> List[dict]:
    if not items:
        return [{item_key: {}}]
    return [{item_key: item} for item in items]


def build_iam_users(bundle: DiscoveryBundle) -> List[dict]:
    users = _load_latest_service_list(bundle.root, "iam", "iam_users_*.json", ("users",))
    return _rows_from_list(users, "user")


def build_iam_groups(bundle: DiscoveryBundle) -> List[dict]:
    groups = _load_latest_service_list(bundle.root, "iam", "iam_groups_*.json", ("groups",))
    return _rows_from_list(groups, "group")


def build_iam_roles(bundle: DiscoveryBundle) -> List[dict]:
    roles = _load_latest_service_list(bundle.root, "iam", "iam_roles_*.json", ("roles",))
    return _rows_from_list(roles, "role")


def build_iam_resource_roles(bundle: DiscoveryBundle) -> List[dict]:
    roles = _load_latest_service_list(
        bundle.root, "iam", "iam_resource_roles_*.json", ("resourceRoles",)
    )
    return _rows_from_list(roles, "resourceRole")


def build_iam_machine_users(bundle: DiscoveryBundle) -> List[dict]:
    users = _load_latest_service_list(
        bundle.root, "iam", "iam_machine_users_*.json", ("machineUsers",)
    )
    return _rows_from_list(users, "machineUser")


def build_iam_env_assignees(bundle: DiscoveryBundle) -> List[dict]:
    assignees = _load_latest_service_list(
        bundle.root,
        "iam",
        "iam_env_resource_assignees_*.json",
        ("resourceAssignees", "assignees"),
    )
    return _rows_from_list(assignees, "assignee")


def build_audit_archive_runs(bundle: DiscoveryBundle) -> List[dict]:
    runs = _load_latest_service_list(
        bundle.root, "audit", "audit_recent_runs_*.json", ("archiveRuns", "runs")
    )
    return _rows_from_list(runs, "run")


def build_audit_outstanding_batches(bundle: DiscoveryBundle) -> List[dict]:
    batches = _load_latest_service_list(
        bundle.root, "audit", "audit_outstanding_batches_*.json", ("batches", "archiveBatches")
    )
    return _rows_from_list(batches, "batch")


def build_rm_policies(bundle: DiscoveryBundle) -> List[dict]:
    policies = _load_latest_service_list(
        bundle.root, "replicationmanager", "rm_policies_*.json", ("policies",)
    )
    return _rows_from_list(policies, "policy")


def build_rm_clusters(bundle: DiscoveryBundle) -> List[dict]:
    clusters = _load_latest_service_list(
        bundle.root, "replicationmanager", "rm_clusters_*.json", ("clusters",)
    )
    return _rows_from_list(clusters, "cluster")


def build_rm_paired_hbase(bundle: DiscoveryBundle) -> List[dict]:
    paired = _load_latest_service_list(
        bundle.root,
        "replicationmanager",
        "rm_paired_hbase_clusters_*.json",
        ("pairedClusters", "clusters"),
    )
    return _rows_from_list(paired, "cluster")


def build_lho_policies(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    lho_root = os.path.join(bundle.root, "lakehouseopt")
    if not os.path.isdir(lho_root):
        return [{"datahub": {}, "policy": {}}]
    for entry in sorted(os.listdir(lho_root)):
        dh_dir = os.path.join(lho_root, entry)
        if not os.path.isdir(dh_dir):
            continue
        for path in sorted(glob(os.path.join(dh_dir, "lho_policies_*.json")), reverse=True):
            doc = load_json(path)
            if not doc:
                continue
            datahub = {"clusterName": entry, "crn": doc.get("datahubCrn")}
            policies = doc.get("policies") or []
            if not policies:
                rows.append({"datahub": datahub, "policy": {}})
                continue
            for policy in policies:
                rows.append({"datahub": datahub, "policy": policy})
            break
    if not rows:
        return [{"datahub": {}, "policy": {}}]
    return rows


def build_lho_health(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    lho_root = os.path.join(bundle.root, "lakehouseopt")
    if not os.path.isdir(lho_root):
        return [{"datahub": {}, "health": {}}]
    for entry in sorted(os.listdir(lho_root)):
        dh_dir = os.path.join(lho_root, entry)
        if not os.path.isdir(dh_dir):
            continue
        for path in sorted(glob(os.path.join(dh_dir, "lho_health_*.json")), reverse=True):
            doc = load_json(path)
            if doc:
                rows.append({"datahub": {"clusterName": entry}, "health": doc})
            break
    if not rows:
        return [{"datahub": {}, "health": {}}]
    return rows


def build_datacatalog_shares(bundle: DiscoveryBundle) -> List[dict]:
    shares = _load_latest_service_list(
        bundle.root, "datacatalog", "dc_data_shares_*.json", ("dataShares", "shares")
    )
    return _rows_from_list(shares, "share")


def build_datacatalog_external_users(bundle: DiscoveryBundle) -> List[dict]:
    users = _load_latest_service_list(
        bundle.root, "datacatalog", "dc_external_users_*.json", ("externalUsers", "users")
    )
    return _rows_from_list(users, "user")


def build_dfw_flow_drafts(bundle: DiscoveryBundle) -> List[dict]:
    drafts = _load_latest_service_list(
        bundle.root, "dfworkload", "dfw_flow_drafts_*.json", ("flowDrafts",)
    )
    return _rows_from_list(drafts, "draft")


def build_dfw_deployments(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    dep_root = os.path.join(bundle.root, "dfworkload", "deployments")
    if not os.path.isdir(dep_root):
        return [{"deployment": {}, "config": {}}]
    for entry in sorted(os.listdir(dep_root)):
        sub = os.path.join(dep_root, entry)
        if not os.path.isdir(sub):
            continue
        for path in sorted(glob(os.path.join(sub, "deployment_config_*.json")), reverse=True):
            doc = load_json(path)
            if doc:
                rows.append({"deployment": {"name": entry}, "config": doc})
            break
    if not rows:
        return [{"deployment": {}, "config": {}}]
    return rows


def build_datalake_backups(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for dl in bundle.datalakes:
        datalake = dl.main_json.get("datalake", {})
        backups_doc = _load_sidecar_json(dl.folder, "Backups")
        backups = backups_doc.get("backups") or []
        if not backups:
            rows.append({"environment": env, "datalake": datalake, "backup": {}})
            continue
        for backup in backups:
            rows.append({"environment": env, "datalake": datalake, "backup": backup})
    return rows


def build_datahub_scaling_activities(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        doc = _load_sidecar_json(dh.folder, "ScalingActivities")
        activities = doc.get("scalingActivities") or doc.get("activities") or []
        if not activities:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "activity": {},
            })
            continue
        for activity in activities:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "activity": activity,
            })
    return rows


def _load_env_sidecar(root: str, marker: str) -> dict:
    env_dir = os.path.join(root, "environment")
    if not os.path.isdir(env_dir):
        return {}
    return _load_sidecar_json(env_dir, marker)


def build_consumption_usage(bundle: DiscoveryBundle) -> List[dict]:
    records = _load_latest_service_list(
        bundle.root, "consumption", "consumption_usage_*.json",
        ("computeUsageRecords", "records"),
    )
    return _rows_from_list(records, "usageRecord")


def build_compute_clusters(bundle: DiscoveryBundle) -> List[dict]:
    clusters = _load_latest_service_list(
        bundle.root, "compute", "compute_clusters_*.json", ("clusters",)
    )
    return _rows_from_list(clusters, "cluster")


def build_compute_deployments(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    clusters_dir = os.path.join(bundle.root, "compute", "clusters")
    if os.path.isdir(clusters_dir):
        for path in sorted(glob(os.path.join(clusters_dir, "**", "deployment_*.json"), recursive=True)):
            doc = load_json(path)
            if not doc:
                continue
            deployment = doc.get("deployment") or doc
            rows.append({"deployment": deployment})
    if not rows:
        return [{"deployment": {}}]
    return rows


def build_env_credentials(bundle: DiscoveryBundle) -> List[dict]:
    doc = _load_env_sidecar(bundle.root, "Credentials")
    credentials = doc.get("credentials") or doc.get("environmentCredentials") or []
    if not credentials and doc:
        return [{"credential": doc}]
    return _rows_from_list(credentials, "credential")


def build_env_proxy_configs(bundle: DiscoveryBundle) -> List[dict]:
    doc = _load_env_sidecar(bundle.root, "ProxyConfigs")
    configs = doc.get("proxyConfigs") or doc.get("configs") or []
    return _rows_from_list(configs, "proxyConfig")


def build_datahub_cluster_definitions(bundle: DiscoveryBundle) -> List[dict]:
    definitions = _load_latest_service_list(
        bundle.root,
        "datahub",
        "ENV_*_ClusterDefinitions_*.json",
        ("clusterDefinitions", "definitions"),
    )
    return _rows_from_list(definitions, "definition")


def build_datahub_scaling_details(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    primary_dl = bundle.datalakes[0].main_json.get("datalake", {}) if bundle.datalakes else {}
    for dh in bundle.datahubs:
        cluster = dh.main_json.get("cluster", {})
        doc = _load_sidecar_json(dh.folder, "ScalingActivityDetails")
        details = doc.get("scalingActivityDetails") or doc.get("details") or []
        if not details:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "detail": {},
            })
            continue
        for detail in details:
            rows.append({
                "environment": env,
                "datalake": primary_dl,
                "cluster": cluster,
                "detail": detail.get("scalingActivity") or detail,
            })
    return rows


def build_cdw_events(bundle: DiscoveryBundle) -> List[dict]:
    rows: List[dict] = []
    env = (bundle.environment or {}).get("environment", {})
    for cdw in bundle.cdws:
        cluster = cdw.main_json.get("cluster", cdw.main_json)
        cluster_name = cdw.name
        cluster_dir = cdw.folder
        for marker, list_key in (
            ("cdw_cluster_events_", "events"),
            ("cdw_dbc_events_", "events"),
            ("cdw_vw_events_", "events"),
        ):
            for path in sorted(glob(os.path.join(cluster_dir, f"{marker}*.json"))):
                doc = load_json(path)
                if not doc:
                    continue
                events = doc.get(list_key) or []
                for event in events:
                    rows.append({
                        "environment": env,
                        "clusterName": cluster_name,
                        "cluster": cluster,
                        "event": event,
                    })
    if not rows:
        return [{"environment": env if bundle.environment else {}, "clusterName": "", "cluster": {}, "event": {}}]
    return rows


def _load_diagnostic_job_docs(root: str, patterns: tuple) -> List[dict]:
    docs: List[dict] = []
    for pattern in patterns:
        for path in sorted(glob(os.path.join(root, pattern)), reverse=True):
            doc = load_json(path)
            if doc:
                docs.append(doc)
    return docs


def _diagnostic_job_rows(docs: List[dict]) -> List[dict]:
    if not docs:
        return [{"job": {}}]
    return [{"job": doc} for doc in docs]


def build_freeipa_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        ("environment/*_DiagnosticCollect_*.json", "environment/*_DiagnosticOperation_*.json"),
    )
    return _diagnostic_job_rows(docs)


def build_datalake_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        (
            "datalake/*/*_DiagnosticCollect_*.json",
            "datalake/*/*_DiagnosticOperation_*.json",
        ),
    )
    return _diagnostic_job_rows(docs)


def build_datahub_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        (
            "datahub/*/*_DiagnosticCollect_*.json",
            "datahub/*/*_DiagnosticOperation_*.json",
        ),
    )
    return _diagnostic_job_rows(docs)


def build_cdw_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        (
            "cdw/*/cdw_diagnostic_jobs_*.json",
            "cdw/*/*_DiagnosticJobDescribes_*.json",
            "cdw/*/cdw_dbc_diagnostic_jobs_*.json",
            "cdw/*/cdw_vw_diagnostic_jobs_*.json",
        ),
    )
    return _diagnostic_job_rows(docs)


def build_cod_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        (
            "cod/*/*_DiagnosticCollect_*.json",
            "cod/*/*_DiagnosticOperation_*.json",
        ),
    )
    return _diagnostic_job_rows(docs)


def build_rm_diagnostic_jobs(bundle: DiscoveryBundle) -> List[dict]:
    docs = _load_diagnostic_job_docs(
        bundle.root,
        ("replicationmanager/clusters/*/*_DiagnosticCollect_*.json",),
    )
    return _diagnostic_job_rows(docs)


def build_dfw_reporting_tasks(bundle: DiscoveryBundle) -> List[dict]:
    tasks = _load_latest_service_list(
        bundle.root,
        "dfworkload",
        "dfw_reporting_tasks_*.json",
        ("reportingTasks", "tasks"),
    )
    return _rows_from_list(tasks, "task")


BUILDERS: Dict[str, callable] = {
    "ENVIRONMENT": build_environment,
    "FREEIPA":     build_freeipa,
    "DATALAKE":    build_datalake,
    "DATALAKE_HEALTH": build_datalake_health,
    "DATALAKE_HOSTS": build_datalake_hosts,
    "DATAHUBS":    build_datahubs,
    "DATAHUB_HEALTH": build_datahub_health,
    "DATAHUB_HOSTS": build_datahub_hosts,
    "DATAHUB_AUTOSCALE_HISTORY": build_datahub_autoscale_history,
    "DATAHUB_LIFECYCLE": build_datahub_lifecycle,
    "DATABASES":   build_databases,
    "CMLCAI":      build_cmlcai,
    "CAI_INSTANCES": build_cai_instances,
    "CAI_SERVING": build_cai_serving,
    "CAI_REGISTRY": build_cai_registry,
    "CAI_SERVING_ACCESS": build_cai_serving_access,
    "CAI_REGISTRY_ACCESS": build_cai_registry_access,
    "CDW":         build_cdw,
    "CDW_DBC":     build_cdw_dbc,
    "CDW_VW":      build_cdw_vw,
    "CDW_DVIZ":    build_cdw_dviz,
    "CDW_HUE":     build_cdw_hue,
    "CDE":         build_cde,
    "CDE_VC":      build_cde_vc,
    "CDE_BACKUPS": build_cde_backups,
    "CDF":         build_cdf,
    "CDF_FLOWS":   build_cdf_flows,
    "CDF_PROJECTS": build_cdf_projects,
    "CDF_READYFLOWS": build_cdf_readyflows,
    "CDF_DEPLOYMENT_EVENTS": build_cdf_deployment_events,
    "CDF_DEPLOYMENT_ALERTS": build_cdf_deployment_alerts,
    "COD":         build_cod,
    "COD_OPDB":    build_cod_opdb,
    "COD_DATAHUB_HEALTH": build_cod_datahub_health,
    "IAM_USERS": build_iam_users,
    "IAM_GROUPS": build_iam_groups,
    "IAM_ROLES": build_iam_roles,
    "IAM_RESOURCE_ROLES": build_iam_resource_roles,
    "IAM_MACHINE_USERS": build_iam_machine_users,
    "IAM_ENV_ASSIGNEES": build_iam_env_assignees,
    "AUDIT_ARCHIVE_RUNS": build_audit_archive_runs,
    "AUDIT_OUTSTANDING_BATCHES": build_audit_outstanding_batches,
    "RM_POLICIES": build_rm_policies,
    "RM_CLUSTERS": build_rm_clusters,
    "RM_PAIRED_HBASE": build_rm_paired_hbase,
    "LHO_POLICIES": build_lho_policies,
    "LHO_HEALTH": build_lho_health,
    "DATACATALOG_SHARES": build_datacatalog_shares,
    "DATACATALOG_EXTERNAL_USERS": build_datacatalog_external_users,
    "DFW_FLOW_DRAFTS": build_dfw_flow_drafts,
    "DFW_DEPLOYMENTS": build_dfw_deployments,
    "DATALAKE_BACKUPS": build_datalake_backups,
    "DATAHUB_SCALING_ACTIVITIES": build_datahub_scaling_activities,
    "CONSUMPTION_USAGE": build_consumption_usage,
    "COMPUTE_CLUSTERS": build_compute_clusters,
    "COMPUTE_DEPLOYMENTS": build_compute_deployments,
    "ENV_CREDENTIALS": build_env_credentials,
    "ENV_PROXY_CONFIGS": build_env_proxy_configs,
    "DATAHUB_CLUSTER_DEFINITIONS": build_datahub_cluster_definitions,
    "DATAHUB_SCALING_DETAILS": build_datahub_scaling_details,
    "CDW_EVENTS": build_cdw_events,
    "FREEIPA_DIAGNOSTIC_JOBS": build_freeipa_diagnostic_jobs,
    "DATALAKE_DIAGNOSTIC_JOBS": build_datalake_diagnostic_jobs,
    "DATAHUB_DIAGNOSTIC_JOBS": build_datahub_diagnostic_jobs,
    "CDW_DIAGNOSTIC_JOBS": build_cdw_diagnostic_jobs,
    "COD_DIAGNOSTIC_JOBS": build_cod_diagnostic_jobs,
    "RM_DIAGNOSTIC_JOBS": build_rm_diagnostic_jobs,
    "DFW_REPORTING_TASKS": build_dfw_reporting_tasks,
}
