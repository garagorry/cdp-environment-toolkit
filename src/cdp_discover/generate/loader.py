"""loader — locate JSON assets produced by ``cdp-discover discover``.

The discovery output layout is::

    <root>/
      environment/<env>.json
      datalake/<dl-name>/<...DL...>.json + ..._DB_*.json
      datahub/<dh-name>/<...DH...>.json
      cdw/<cluster>/<...CDW...>.json + database_catalogs/ + virtual_warehouses/
      cai/<workspace>/<...CAI...>.json
      cde/<service>/<...CDE...>.json   (optional)
      cdf/<service>/<...CDF...>.json + deployments/
      cod/<database>/<...COD...>.json

This module is fault tolerant: missing services do not break the report.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from glob import glob
from typing import Dict, List, Optional

from .common import load_json


@dataclass
class ServiceAsset:
    name: str
    folder: str
    main_json: dict
    extras: Dict[str, dict] = field(default_factory=dict)


@dataclass
class DiscoveryBundle:
    root: str
    environment: Optional[dict] = None
    freeipa_upgrade_options: Optional[dict] = None
    datalakes: List[ServiceAsset] = field(default_factory=list)
    datahubs: List[ServiceAsset] = field(default_factory=list)
    cdws: List[ServiceAsset] = field(default_factory=list)
    cais: List[ServiceAsset] = field(default_factory=list)
    cdes: List[ServiceAsset] = field(default_factory=list)
    cdfs: List[ServiceAsset] = field(default_factory=list)
    cods: List[ServiceAsset] = field(default_factory=list)
    databases: List[dict] = field(default_factory=list)


def _pick_main_json(folder: str, marker: str) -> Optional[str]:
    """Inside a service folder, the "main" JSON is the one whose filename
    contains ``_<marker>_<name>_<timestamp>.json`` and no further suffix."""
    candidates = sorted(glob(os.path.join(folder, f"*_{marker}_*.json")))
    if not candidates:
        return None
    # prefer files where the basename (without timestamp) matches the folder name
    folder_name = os.path.basename(folder.rstrip("/"))
    for c in candidates:
        if f"_{marker}_{folder_name}_" in os.path.basename(c):
            base = os.path.basename(c)
            if all(suffix not in base for suffix in (
                "_AvailableImages_",
                "_RunTimeAvailableImages_",
                "_Template_",
                "_DB_",
                "_FreeIPAUpgradeOptions_",
                "_AuthorizedIPRanges_",
                "_InstanceGroupTags_",
                "_InstanceGroups_",
                "_Instances_",
                "_LBSubnets_",
                "_Subnets_",
                "_Summary_",
                "_Tags_",
                "_backupMetadata_",
                "_upgradeState_",
                "deployments_list_",
                "flow_definitions_",
                "projects_",
                "readyflows_",
                "_DataHub_",
                "_Upgrade_",
                "_ClientConnectivity_",
                "_Snapshots_",
                "_ServiceStatus_",
                "_LifecycleEvents_",
                "_HostStatus_",
                "_AutoScaleRules_",
                "_AutoScaleHistory_",
                "datalake_runtimes_",
                "_RestoreSnapshots_",
                "_Diagnostics_",
                "_DeploymentEvents_",
                "_DeploymentAlerts_",
                "cdw_backup_entities_",
                "cdw_backups_",
                "backup_describe_",
                "backup_logs_",
                "restores_list_",
                "restore_describe_",
                "_DiagnosticsList_",
                "_ScalingActivities_",
                "_SuspendResumeStatus_",
                "_KubeconfigMeta_",
                "_FreeIPAStatus_",
                "_IdBrokerMappings_",
                "_ConnectedDataServices_",
                "_FreeIPADiagnosticsList_",
                "cdw_diagnostic_jobs_",
                "cdw_cluster_events_",
                "cdw_configs_list_",
                "cdw_config_describe_",
                "cdw_dbc_events_",
                "cdw_vw_events_",
                "_ClusterDefinitions_",
                "_ScalingActivityDetails_",
                "_Credentials_",
                "_AccountTelemetry_",
                "_ProxyConfigs_",
                "consumption_usage_",
                "compute_clusters_",
                "cluster_describe_",
                "deployment_",
                "_DiagnosticCollect_",
                "_DiagnosticOperation_",
                "_DiagnosticJobDescribes_",
                "dfw_reporting_tasks_",
                "cdw_dbc_diagnostic_jobs_",
                "cdw_vw_diagnostic_jobs_",
                "dc_",
                "dfw_",
                "_LatestVersion_",
                "_Backups_",
                "_Access_",
                "_HealthInfo_",
                "hue_instances_",
                "data_visualizations_",
                "dbcs_list_",
                "vws_list_",
                "ml_serving_apps_list_",
                "model_registries_list_",
                "_UpgradeStatus_",
                "_Backups_",
                "_Kubeconfig_",
                "_InitLogs_",
                "_InstanceInfo_",
                "deployments_list_",
                "flows_list_",
                "projects_list_",
                "readyflows_list_",
            )):
                return c
    return candidates[0]


def _load_service_folders(parent: str, marker: str) -> List[ServiceAsset]:
    if not os.path.isdir(parent):
        return []
    out: List[ServiceAsset] = []
    for entry in sorted(os.listdir(parent)):
        sub = os.path.join(parent, entry)
        if not os.path.isdir(sub):
            continue
        main = _pick_main_json(sub, marker)
        if not main:
            continue
        doc = load_json(main)
        if not doc:
            continue
        extras: Dict[str, dict] = {}
        for extra_key in ("AvailableImages", "RunTimeAvailableImages", "Template", "DB"):
            for f in glob(os.path.join(sub, f"*_{extra_key}_*.json")):
                d = load_json(f)
                if d is not None:
                    extras[extra_key] = d
        out.append(ServiceAsset(name=entry, folder=sub, main_json=doc, extras=extras))
    return out


def find_assets(root: str) -> DiscoveryBundle:
    """Walk a discovery output directory and return everything we can use."""
    root = os.path.abspath(root)
    bundle = DiscoveryBundle(root=root)

    env_dir = os.path.join(root, "environment")
    if os.path.isdir(env_dir):
        env_files = sorted(
            f for f in glob(os.path.join(env_dir, "ENV_*.json"))
            if "_FreeIPAUpgradeOptions_" not in os.path.basename(f)
        )
        if env_files:
            bundle.environment = load_json(env_files[0])
        for f in glob(os.path.join(env_dir, "*_FreeIPAUpgradeOptions_*.json")):
            bundle.freeipa_upgrade_options = load_json(f)
            break

    bundle.datalakes = _load_service_folders(os.path.join(root, "datalake"), "DL")
    bundle.datahubs = _load_service_folders(os.path.join(root, "datahub"), "DH")
    bundle.cdws = _load_service_folders(os.path.join(root, "cdw"), "CDW")
    bundle.cais = _load_service_folders(os.path.join(root, "cai"), "CAI")
    bundle.cdes = _load_service_folders(os.path.join(root, "cde"), "CDE")
    bundle.cdfs = _load_service_folders(os.path.join(root, "cdf"), "CDF")
    bundle.cods = _load_service_folders(os.path.join(root, "cod"), "COD")

    for dl in bundle.datalakes:
        db_doc = dl.extras.get("DB")
        if db_doc:
            db_doc.setdefault("__owner__", {
                "type": "DATALAKE",
                "name": dl.name,
            })
            bundle.databases.append(db_doc)

    return bundle


def summarize(bundle: DiscoveryBundle) -> str:
    """Short text summary, used by the CLI for a sanity check."""
    has_env = "yes" if bundle.environment else "no"
    tier2 = []
    tier3 = []
    for name in ("iam", "audit", "replicationmanager", "lakehouseopt"):
        if os.path.isdir(os.path.join(bundle.root, name)):
            tier2.append(name)
    for name in ("datacatalog", "dfworkload"):
        if os.path.isdir(os.path.join(bundle.root, name)):
            tier3.append(name)
    tier4 = []
    for name in ("consumption", "compute"):
        if os.path.isdir(os.path.join(bundle.root, name)):
            tier4.append(name)
    tier2_line = f"\nTier 2 modules : {', '.join(tier2) if tier2 else 'none'}"
    tier3_line = f"\nTier 3 modules : {', '.join(tier3) if tier3 else 'none'}"
    tier4_line = f"\nTier 4 modules : {', '.join(tier4) if tier4 else 'none'}"
    return (
        f"Discovery root : {bundle.root}\n"
        f"Environment    : {has_env}\n"
        f"Datalakes      : {len(bundle.datalakes)}\n"
        f"Datahubs       : {len(bundle.datahubs)}\n"
        f"CDW clusters   : {len(bundle.cdws)}\n"
        f"CAI workspaces : {len(bundle.cais)}\n"
        f"CDE services   : {len(bundle.cdes)}\n"
        f"CDF services   : {len(bundle.cdfs)}\n"
        f"COD databases  : {len(bundle.cods)}\n"
        f"External DBs   : {len(bundle.databases)}"
        f"{tier2_line}"
        f"{tier3_line}"
        f"{tier4_line}"
    )
