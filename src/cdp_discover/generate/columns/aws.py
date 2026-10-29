"""columns_aws — column specifications for the AWS-flavoured upgrade report.

Each entry is a ``Column`` (group, label, accessor). The Excel writer renders
``group`` as a merged banner row above ``label``, then writes one cell per row
using ``accessor``. ``accessor`` is either:

* a dotted path string (resolved against the row's "record")
* a callable ``f(record) -> value``

Group names should match the visual sections of the template
(ENVIRONMENT / NETWORK / STORAGE / SECURITY / FREEIPA / TAGS / IMAGE / ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from ..common import Accessor, account_id_from_crn, at, first, join_list, parse_iso_date


@dataclass(frozen=True)
class Column:
    group: str
    label: str
    accessor: Accessor


def _crn_account(path: str):
    inner = at(path)
    return lambda rec: account_id_from_crn(inner(rec) or "")


def _join(path: str, sep: str = ", ", key: str | None = None):
    inner = at(path)
    return lambda rec: join_list(inner(rec), sep=sep, key=key)


def _date(path: str):
    inner = at(path)
    return lambda rec: parse_iso_date(inner(rec))


def _health_checks(path: str = "service.healthChecks"):
    inner = at(path)

    def _fmt(rec):
        checks = inner(rec) or []
        if not isinstance(checks, list):
            return checks
        return "; ".join(
            f"{c.get('name', '?')}={c.get('summary', '?')}"
            for c in checks
            if isinstance(c, dict)
        )

    return _fmt


# -------------------------------------------------------------------------
# ENVIRONMENT sheet (one row per environment file)
# -------------------------------------------------------------------------
ENVIRONMENT: List[Column] = [
    Column("Identity",   "Type",                 lambda r: "ENVIRONMENT"),
    Column("Identity",   "Environment Name",     "environment.environmentName"),
    Column("Identity",   "Environment CRN",      "environment.crn"),
    Column("Identity",   "Account ID",           _crn_account("environment.crn")),
    Column("Identity",   "Region",               "environment.region"),
    Column("Identity",   "Cloud Provider",       "environment.cloudPlatform"),
    Column("Identity",   "Status",               "environment.status"),
    Column("Identity",   "Credential Name",      "environment.credentialName"),
    Column("Identity",   "Description",          "environment.description"),
    Column("Identity",   "Created",              _date("environment.created")),
    Column("Identity",   "Creator",              "environment.creator"),
    Column("Identity",   "Workload Analytics",   "environment.workloadAnalytics"),
    Column("Identity",   "Report Deployment Logs","environment.reportDeploymentLogs"),

    Column("Network",    "Network Name",         "environment.network.networkName"),
    Column("Network",    "VPC ID",               "environment.network.aws.vpcId"),
    Column("Network",    "Network CIDR",         "environment.network.networkCidr"),
    Column("Network",    "Subnet IDs",           _join("environment.network.subnetIds")),
    Column("Network",    "Endpoint Gateway Scheme","environment.network.endpointAccessGatewayScheme"),
    Column("Network",    "Endpoint Gateway Subnets",_join("environment.network.endpointAccessGatewaySubnetIds")),
    Column("Network",    "Subnet Metadata",      "environment.network.subnetMetadata"),

    Column("Storage",    "Log Storage Enabled",  "environment.logStorage.enabled"),
    Column("Storage",    "Log Storage Location", "environment.logStorage.awsDetails.storageLocationBase"),
    Column("Storage",    "Log Instance Profile", "environment.logStorage.awsDetails.instanceProfile"),
    Column("Storage",    "Backup Storage Enabled","environment.backupStorage.enabled"),
    Column("Storage",    "Backup Storage Location","environment.backupStorage.awsDetails.storageLocationBase"),
    Column("Storage",    "Backup Instance Profile","environment.backupStorage.awsDetails.instanceProfile"),

    Column("Security",   "Security Access CIDR", "environment.securityAccess.cidr"),
    Column("Security",   "SSH Login User",       "environment.authentication.loginUserName"),
    Column("Security",   "SSH Public Key",       "environment.authentication.publicKeyId"),

    Column("FreeIPA",    "FreeIPA CRN",          "environment.freeipa.crn"),
    Column("FreeIPA",    "FreeIPA Domain",       "environment.freeipa.domain"),
    Column("FreeIPA",    "FreeIPA Hostname",     "environment.freeipa.hostname"),
    Column("FreeIPA",    "FreeIPA Server IPs",   _join("environment.freeipa.serverIP")),
    Column("FreeIPA",    "FreeIPA Recipes",      _join("environment.freeipa.recipes")),
    Column("FreeIPA",    "FreeIPA Instance Count","environment.freeipa.instanceCountByGroup"),
    Column("FreeIPA",    "FreeIPA MultiAZ",      "environment.freeipa.multiAz"),
    Column("FreeIPA",    "FreeIPA Image ID",     "environment.freeipa.imageDetails.imageId"),
    Column("FreeIPA",    "FreeIPA Image OS",     "environment.freeipa.imageDetails.imageOs"),
    Column("FreeIPA",    "FreeIPA Image Catalog","environment.freeipa.imageDetails.imageCatalogName"),

    Column("Tags",       "Tags - User Defined",  "environment.tags.userDefined"),
    Column("Tags",       "Tags - Defaults",      "environment.tags.defaults"),
]


# -------------------------------------------------------------------------
# FREEIPA sheet (one row per FreeIPA instance)
# -------------------------------------------------------------------------
FREEIPA: List[Column] = [
    Column("Environment","Environment Name",     "environment.environmentName"),
    Column("Environment","Environment CRN",      "environment.crn"),
    Column("FreeIPA",    "FreeIPA CRN",          "environment.freeipa.crn"),
    Column("FreeIPA",    "FreeIPA Domain",       "environment.freeipa.domain"),
    Column("FreeIPA",    "Recipes",              _join("environment.freeipa.recipes")),

    Column("Instance",   "Discovery FQDN",       "instance.discoveryFQDN"),
    Column("Instance",   "Instance ID",          "instance.instanceId"),
    Column("Instance",   "Instance Group",       "instance.instanceGroup"),
    Column("Instance",   "Instance Type",        "instance.instanceType"),
    Column("Instance",   "VM Type",              "instance.instanceVmType"),
    Column("Instance",   "Status",               "instance.instanceStatus"),
    Column("Instance",   "Lifecycle",            "instance.lifeCycle"),
    Column("Instance",   "Availability Zone",    "instance.availabilityZone"),
    Column("Instance",   "Private IP",           "instance.privateIP"),
    Column("Instance",   "Public IP",            "instance.publicIP"),
    Column("Instance",   "SSH Port",             "instance.sshPort"),
    Column("Instance",   "Subnet ID",            "instance.subnetId"),
    Column("Instance",   "Attached Volumes",     "instance.attachedVolumes"),

    Column("Image",      "Image Catalog URL",    "environment.freeipa.imageDetails.imageCatalogName"),
    Column("Image",      "Image ID",             "environment.freeipa.imageDetails.imageId"),
    Column("Image",      "Image OS",             "environment.freeipa.imageDetails.imageOs"),
]


# -------------------------------------------------------------------------
# DATALAKE sheet (one row per DL instance, joined with DL header context)
# -------------------------------------------------------------------------
def _product_versions(rec):
    versions = at("datalake.productVersions")(rec) or []
    return ", ".join(f"{p.get('name','?')}={p.get('version','?')}" for p in versions)


DATALAKE: List[Column] = [
    Column("Environment","Environment Name",     "environment.environmentName"),
    Column("Environment","Environment CRN",      "environment.crn"),

    Column("Datalake",   "Datalake Name",        "datalake.datalakeName"),
    Column("Datalake",   "Datalake CRN",         "datalake.crn"),
    Column("Datalake",   "Status",               "datalake.status"),
    Column("Datalake",   "Status Reason",        "datalake.statusReason"),
    Column("Datalake",   "Shape",                "datalake.shape"),
    Column("Datalake",   "Cloud Platform",       "datalake.cloudPlatform"),
    Column("Datalake",   "Creation Date",        _date("datalake.creationDate")),
    Column("Datalake",   "Product Versions",     _product_versions),
    Column("Datalake",   "CM Version",           "datalake.clouderaManager.version"),
    Column("Datalake",   "CM Repo URL",          "datalake.clouderaManager.clouderaManagerRepositoryURL"),
    Column("Datalake",   "Storage Base",         "datalake.cloudStorageBaseLocation"),
    Column("Datalake",   "RAZ Enabled",          "datalake.enableRangerRaz"),
    Column("Datalake",   "AWS IDBroker Profile", "datalake.awsConfiguration.instanceProfile"),

    Column("Instance Group","Instance Group Name","group.name"),
    Column("Instance Group","Group Recipes",     _join("group.recipes")),
    Column("Instance Group","Availability Zones",_join("group.availabilityZones")),

    Column("Instance",   "Instance ID",          "instance.id"),
    Column("Instance",   "FQDN",                 "instance.discoveryFQDN"),
    Column("Instance",   "State",                "instance.state"),
    Column("Instance",   "Service Status",       "instance.instanceStatus"),
    Column("Instance",   "Status Reason",        "instance.statusReason"),
    Column("Instance",   "Cloudera Manager",     "instance.clouderaManagerServer"),
    Column("Instance",   "Instance Group",       "instance.instanceGroup"),
    Column("Instance",   "Instance Role",        "instance.instanceTypeVal"),
    Column("Instance",   "VM Type",              "instance.instanceVmType"),
    Column("Instance",   "Private IP",           "instance.privateIp"),
    Column("Instance",   "Public IP",            "instance.publicIp"),
    Column("Instance",   "SSH Port",             "instance.sshPort"),
    Column("Instance",   "Availability Zone",    "instance.availabilityZone"),
    Column("Instance",   "Subnet ID",            "instance.subnetId"),
    Column("Instance",   "Rack ID",              "instance.rackId"),
    Column("Instance",   "Attached Volumes",     "instance.attachedVolumes"),

    Column("Image",      "Image AMI",            "datalake.imageDetails.imageName"),
    Column("Image",      "Image ID",             "datalake.imageDetails.imageId"),
    Column("Image",      "Image Catalog",        "datalake.imageDetails.imageCatalogName"),
]


# -------------------------------------------------------------------------
# DATALAKE_HEALTH — CM service health from get-cluster-service-status
# -------------------------------------------------------------------------
DATALAKE_HEALTH: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",      "environment.crn"),

    Column("Datalake",    "Datalake Name",        "datalake.datalakeName"),
    Column("Datalake",    "Datalake CRN",         "datalake.crn"),
    Column("Datalake",    "Status",               "datalake.status"),
    Column("Datalake",    "Status Reason",        "datalake.statusReason"),

    Column("Service",     "Service Type",         "service.type"),
    Column("Service",     "State",                "service.state"),
    Column("Service",     "Health Summary",       "service.healthSummary"),
    Column("Service",     "Health Checks",        _health_checks()),
]


# -------------------------------------------------------------------------
# DATALAKE_HOSTS — CM host health from get-cluster-host-status
# -------------------------------------------------------------------------
DATALAKE_HOSTS: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",      "environment.crn"),

    Column("Datalake",    "Datalake Name",        "datalake.datalakeName"),
    Column("Datalake",    "Datalake CRN",         "datalake.crn"),
    Column("Datalake",    "Status",               "datalake.status"),

    Column("Host",        "Host ID",              "host.hostid"),
    Column("Host",        "Hostname",             "host.hostname"),
    Column("Host",        "Health Summary",       "host.healthSummary"),
]


# -------------------------------------------------------------------------
# DATAHUBS sheet (one row per DH instance, joined with cluster context)
# -------------------------------------------------------------------------
DATAHUBS: List[Column] = [
    Column("Environment","Environment Name",     "environment.environmentName"),
    Column("Environment","Environment CRN",      "environment.crn"),
    Column("Environment","Datalake Name",        "datalake.datalakeName"),

    Column("Cluster",    "Cluster Name",         "cluster.clusterName"),
    Column("Cluster",    "Cluster CRN",          "cluster.crn"),
    Column("Cluster",    "Creation Date",        _date("cluster.creationDate")),
    Column("Cluster",    "Status",               "cluster.status"),
    Column("Cluster",    "Cluster Status",       "cluster.clusterStatus"),
    Column("Cluster",    "Status Reason",        "cluster.statusReason"),
    Column("Cluster",    "Node Count",           "cluster.nodeCount"),
    Column("Cluster",    "Workload Type",        "cluster.workloadType"),
    Column("Cluster",    "Cloud Platform",       "cluster.cloudPlatform"),
    Column("Cluster",    "Cluster Template CRN", "cluster.clusterTemplateCrn"),
    Column("Cluster",    "MultiAZ",              "cluster.multiAz"),
    Column("Cluster",    "CM Version",           "cluster.clouderaManager.version"),
    Column("Cluster",    "CDH Platform Version", "cluster.clouderaManager.platformVersion"),

    Column("Instance Group","Instance Group Name","group.name"),
    Column("Instance Group","Group Recipes",     _join("group.recipes")),
    Column("Instance Group","Group Subnet IDs",  _join("group.subnetIds")),
    Column("Instance Group","Availability Zones",_join("group.availabilityZones")),

    Column("Instance",   "Instance ID",          "instance.id"),
    Column("Instance",   "FQDN",                 "instance.fqdn"),
    Column("Instance",   "State",                "instance.state"),
    Column("Instance",   "Service Status",       "instance.status"),
    Column("Instance",   "Status Reason",        "instance.statusReason"),
    Column("Instance",   "Cloudera Manager",     "instance.clouderaManagerServer"),
    Column("Instance",   "Instance Group",       "instance.instanceGroup"),
    Column("Instance",   "Instance Role",        "instance.instanceType"),
    Column("Instance",   "VM Type",              "instance.instanceVmType"),
    Column("Instance",   "Private IP",           "instance.privateIp"),
    Column("Instance",   "Public IP",            "instance.publicIp"),
    Column("Instance",   "SSH Port",             "instance.sshPort"),
    Column("Instance",   "Availability Zone",    "instance.availabilityZone"),
    Column("Instance",   "Subnet ID",            "instance.subnetId"),
    Column("Instance",   "Rack ID",              "instance.rackId"),
    Column("Instance",   "Attached Volumes",     "instance.attachedVolumes"),

    Column("Image",      "Image AMI",            "cluster.imageDetails.name"),
    Column("Image",      "Image ID",             "cluster.imageDetails.id"),
    Column("Image",      "Image OS",             "cluster.imageDetails.os"),
    Column("Image",      "Image Catalog",        "cluster.imageDetails.catalogName"),
    Column("Image",      "Image Catalog URL",    "cluster.imageDetails.catalogUrl"),
]


# -------------------------------------------------------------------------
# DATAHUB_HEALTH — per-cluster CM service health
# -------------------------------------------------------------------------
DATAHUB_HEALTH: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",      "environment.crn"),
    Column("Environment", "Datalake Name",        "datalake.datalakeName"),

    Column("Cluster",     "Cluster Name",         "cluster.clusterName"),
    Column("Cluster",     "Cluster CRN",          "cluster.crn"),
    Column("Cluster",     "Status",               "cluster.status"),
    Column("Cluster",     "Cluster Status",       "cluster.clusterStatus"),
    Column("Cluster",     "Status Reason",        "cluster.statusReason"),
    Column("Cluster",     "Workload Type",        "cluster.workloadType"),

    Column("Service",     "Service Type",         "service.type"),
    Column("Service",     "State",                "service.state"),
    Column("Service",     "Health Summary",       "service.healthSummary"),
    Column("Service",     "Health Checks",        _health_checks()),
]


# -------------------------------------------------------------------------
# DATAHUB_LIFECYCLE — cluster timeline (newest events first)
# -------------------------------------------------------------------------
def _event_cluster_name(rec):
    cluster = rec.get("cluster") or {}
    event = rec.get("event") or {}
    return event.get("clusterName") or cluster.get("clusterName")


DATAHUB_LIFECYCLE: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",      "environment.crn"),
    Column("Environment", "Datalake Name",        "datalake.datalakeName"),

    Column("Cluster",     "Cluster Name",         _event_cluster_name),
    Column("Cluster",     "Cluster CRN",          "cluster.crn"),
    Column("Cluster",     "Current Status",       "cluster.status"),
    Column("Cluster",     "Current Cluster Status", "cluster.clusterStatus"),

    Column("Event",       "Event Type",           "event.eventType"),
    Column("Event",       "Event Time",           _date("event.eventTimestamp")),
    Column("Event",       "Message",              "event.eventMessage"),
    Column("Event",       "Notification Type",    "event.notificationType"),
    Column("Event",       "Stack Status",         "event.stackStatus"),
    Column("Event",       "Cluster Status",       "event.clusterStatus"),
    Column("Event",       "Stack Name",           "event.stackName"),
    Column("Event",       "Blueprint Name",       "event.blueprintName"),
    Column("Event",       "Instance Group",       "event.instanceGroup"),
    Column("Event",       "Node Count",           "event.nodeCount"),
    Column("Event",       "Region",               "event.region"),
    Column("Event",       "Availability Zone",    "event.availabilityZone"),
    Column("Event",       "User ID",              "event.userId"),
    Column("Event",       "User Name",            "event.userName"),
]


# -------------------------------------------------------------------------
# DATAHUB_HOSTS — CM host health per DataHub cluster
# -------------------------------------------------------------------------
DATAHUB_HOSTS: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",      "environment.crn"),
    Column("Environment", "Datalake Name",        "datalake.datalakeName"),

    Column("Cluster",     "Cluster Name",         "cluster.clusterName"),
    Column("Cluster",     "Cluster CRN",          "cluster.crn"),
    Column("Cluster",     "Status",               "cluster.status"),

    Column("Host",        "Host ID",              "host.hostid"),
    Column("Host",        "Hostname",             "host.hostname"),
    Column("Host",        "Health Summary",       "host.healthSummary"),
]


# -------------------------------------------------------------------------
# DATAHUB_AUTOSCALE_HISTORY — autoscale activity timeline
# -------------------------------------------------------------------------
DATAHUB_AUTOSCALE_HISTORY: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Datalake Name",        "datalake.datalakeName"),

    Column("Cluster",     "Cluster Name",         "cluster.clusterName"),
    Column("Cluster",     "Cluster CRN",          "cluster.crn"),

    Column("Event",       "Event Time",           _date("event.eventTime")),
    Column("Event",       "Message",              "event.eventMessage"),
]


# -------------------------------------------------------------------------
# DATABASES sheet (one row per external DB JSON file)
# -------------------------------------------------------------------------
DATABASES: List[Column] = [
    Column("Owner",      "Owner Type",           "__owner__.type"),
    Column("Owner",      "Owner Name",           "__owner__.name"),
    Column("DB Server",  "Name",                 "name"),
    Column("DB Server",  "CRN",                  "crn"),
    Column("DB Server",  "Environment CRN",      "environmentCrn"),
    Column("DB Server",  "Cluster CRN",          "clusterCrn"),
    Column("DB Server",  "Host",                 "host"),
    Column("DB Server",  "Port",                 "port"),
    Column("DB Server",  "Vendor",               "databaseVendor"),
    Column("DB Server",  "Vendor Display",       "databaseVendorDisplayName"),
    Column("DB Server",  "Status",               "status"),
    Column("DB Server",  "Status Reason",        "statusReason"),
    Column("DB Server",  "Resource Status",      "resourceStatus"),
    Column("DB Server",  "Creation Date",        _date("creationDate")),
    Column("SSL",        "SSL Mode",             "sslConfig.sslMode"),
    Column("SSL",        "SSL Cert Type",        "sslConfig.sslCertificateType"),
    Column("SSL",        "SSL Cert Count",       lambda r: len(at("sslConfig.sslCertificates")(r) or [])),
]


# -------------------------------------------------------------------------
# CMLCAI sheet (one row per CAI workspace)
# -------------------------------------------------------------------------
def _tag_value(key: str):
    def _f(rec):
        tags = at("workspace.tags")(rec) or []
        for t in tags:
            if isinstance(t, dict) and t.get("key") == key:
                return t.get("value")
        return None
    return _f


def _all_tags(rec):
    """All workspace tags as ``key=value; ...`` (tag keys vary per customer)."""
    tags = at("workspace.tags")(rec) or []
    pairs = [f"{t.get('key')}={t.get('value')}" for t in tags if isinstance(t, dict) and t.get("key")]
    return "; ".join(pairs) or None


CMLCAI: List[Column] = [
    Column("Workspace",  "Workspace Name",       "workspace.instanceName"),
    Column("Workspace",  "Environment Name",     "workspace.environmentName"),
    Column("Workspace",  "Status",               "workspace.instanceStatus"),
    Column("Workspace",  "Workspace URL",        "workspace.instanceUrl"),
    Column("Workspace",  "Workspace CRN",        "workspace.crn"),
    Column("Workspace",  "Environment CRN",      "workspace.environmentCrn"),
    Column("Workspace",  "K8s Cluster Name",     "workspace.k8sClusterName"),
    Column("Workspace",  "Creator CRN",          "workspace.creatorCrn"),
    Column("Workspace",  "Version",              "workspace.version"),
    Column("Workspace",  "HTTPS Enabled",        "workspace.httpsEnabled"),
    Column("Workspace",  "Public Endpoint",      "workspace.endpointPublicAccess"),
    Column("Workspace",  "Filesystem ID",        "workspace.filesystemID"),
    Column("Workspace",  "Cloud Platform",       "workspace.cloudPlatform"),
    Column("Workspace",  "Monitoring Enabled",   "workspace.monitoringEnabled"),
    Column("Workspace",  "Creation Date",        _date("workspace.creationDate")),
    Column("Workspace",  "Upgrade State",        "workspace.upgradeState"),
    Column("Workspace",  "NFS Version",          "workspace.nfsVersion"),
    Column("Workspace",  "Is Private",           "workspace.isPrivate"),

    Column("Tags",       "Owner",                _tag_value("Owner")),
    Column("Tags",       "All Tags",             _all_tags),

    Column("Network",    "LB IP Whitelists",     _join("workspace.loadBalancerIPWhitelists")),
    Column("Network",    "Authorized IP Ranges", "workspace.authorizedIPRanges"),

    Column("Capacity",   "Instance Groups",      "workspace.instanceGroups"),

    Column("Upgrade",    "Latest Available Version", first(
        "latestVersion.latestAvailableVersion", "latestVersion.version", "latestVersion.latestVersion"
    )),
    Column("Backups",    "Backup Count",           lambda r: len(at("backups.backups")(r) or [])),
    Column("Access",     "Access Grant Count",     lambda r: len(at("access.access")(r) or [])),
]


# -------------------------------------------------------------------------
# CAI_INSTANCES — one row per workspace instance
# -------------------------------------------------------------------------
CAI_INSTANCES: List[Column] = [
    Column("Workspace",  "Workspace Name",       "workspace.instanceName"),
    Column("Workspace",  "Environment Name",     "workspace.environmentName"),
    Column("Workspace",  "Status",               "workspace.instanceStatus"),
    Column("Workspace",  "Version",              "workspace.version"),
    Column("Workspace",  "Workspace CRN",        "workspace.crn"),

    Column("Instance Group", "Group Name",       "group.instanceGroupName"),
    Column("Instance Group", "Instance Type",    "group.instanceType"),
    Column("Instance Group", "Instance Count",   "group.instanceCount"),
    Column("Instance Group", "Min Instances",    "group.minInstances"),
    Column("Instance Group", "Max Instances",    "group.maxInstances"),

    Column("Instance",   "Instance ID",          "instance.instanceId"),
    Column("Instance",   "Availability Zone",    "instance.availabilityZone"),
]


# -------------------------------------------------------------------------
# CAI_SERVING — ML Serving Apps
# -------------------------------------------------------------------------
CAI_SERVING: List[Column] = [
    Column("App",        "App Name",             first("app.appName", "app.name", "app.instanceName")),
    Column("App",        "CRN",                  first("app.crn", "app.appCrn")),
    Column("App",        "Environment Name",     "app.environmentName"),
    Column("App",        "Cluster ID",           "app.clusterId"),
    Column("App",        "Status",               "app.status"),
    Column("App",        "Creator",              "app.creator"),
    Column("App",        "Created",              _date("app.createdAt")),
]


# -------------------------------------------------------------------------
# CAI_REGISTRY — Model Registries
# -------------------------------------------------------------------------
CAI_REGISTRY: List[Column] = [
    Column("Registry",   "Registry Name",        first(
        "registry.modelRegistryName", "registry.registryName", "registry.workspaceName"
    )),
    Column("Registry",   "CRN",                  first("registry.crn", "registry.modelRegistryCrn")),
    Column("Registry",   "Environment Name",     "registry.environmentName"),
    Column("Registry",   "Status",               "registry.status"),
    Column("Registry",   "Version",              "registry.version"),
    Column("Registry",   "Domain",               "registry.domain"),
    Column("Registry",   "Created",              _date("registry.createdAt")),
    Column("Upgrade",    "Latest Registry Version", first(
        "latestVersion.version", "latestVersion.latestVersion"
    )),
]


# -------------------------------------------------------------------------
# CAI_SERVING_ACCESS — ML Serving App access grants
# -------------------------------------------------------------------------
CAI_SERVING_ACCESS: List[Column] = [
    Column("App",        "App Name",             first("resource.appName", "resource.name", "resource.instanceName")),
    Column("App",        "CRN",                  first("resource.crn", "resource.appCrn")),
    Column("Access",     "User CRN",             "access.userCrn"),
    Column("Access",     "Email",                "access.email"),
    Column("Access",     "Role",                 "access.role"),
]


# -------------------------------------------------------------------------
# CAI_REGISTRY_ACCESS — Model Registry access grants
# -------------------------------------------------------------------------
CAI_REGISTRY_ACCESS: List[Column] = [
    Column("Registry",   "Registry Name",        first(
        "resource.modelRegistryName", "resource.registryName", "resource.name"
    )),
    Column("Registry",   "CRN",                  first("resource.crn", "resource.modelRegistryCrn")),
    Column("Access",     "User CRN",             "access.userCrn"),
    Column("Access",     "Email",                "access.email"),
    Column("Access",     "Role",                 "access.role"),
]


# -------------------------------------------------------------------------
# CDW sheet (one row per CDW cluster)
# -------------------------------------------------------------------------
CDW: List[Column] = [
    Column("Cluster",    "Cluster ID",           "cluster.id"),
    Column("Cluster",    "Cluster Name",         "cluster.name"),
    Column("Cluster",    "Status",               "cluster.status"),
    Column("Cluster",    "Cloud Platform",       "cluster.cloudPlatform"),
    Column("Cluster",    "Version",              "cluster.version"),
    Column("Cluster",    "Creation Date",        _date("cluster.creationDate")),
    Column("Cluster",    "Environment CRN",      "cluster.environmentCrn"),
    Column("Cluster",    "Resource Pool",        "cluster.resourcePool"),

    Column("Creator",    "Email",                "cluster.creator.email"),
    Column("Creator",    "Workload Username",    "cluster.creator.workloadUsername"),
    Column("Creator",    "Creator CRN",          "cluster.creator.crn"),

    Column("Support",    "Support Status",       "cluster.productSupport.status"),
    Column("Support",    "Support Expiry",       _date("cluster.productSupport.expiryDate")),
    Column("Support",    "Support Message",      "cluster.productSupport.message"),

    Column("Network",    "Worker Subnet IDs",    _join("cluster.awsOptions.workerSubnetIds")),
    Column("Network",    "LB Subnet IDs",        _join("cluster.awsOptions.lbSubnetIds")),
    Column("Network",    "Availability Zones",   _join("cluster.awsOptions.availabilityZones")),
    Column("Network",    "K8s Access CIDR",      "cluster.whitelistK8sClusterAccessIpCIDRs"),
    Column("Network",    "Workload Access CIDR", "cluster.whitelistWorkloadAccessIpCIDRs"),
    Column("Network",    "Overlay Network",      "cluster.useOverlayNetwork"),
    Column("Network",    "Private Load Balancer","cluster.enablePrivateLoadBalancer"),
    Column("Network",    "Spot Instances",       "cluster.enableSpotInstances"),
]


# -------------------------------------------------------------------------
# CDW_DBC — Database Catalogs
# -------------------------------------------------------------------------
CDW_DBC: List[Column] = [
    Column("Cluster",    "Cluster Name",         "cluster.name"),
    Column("Cluster",    "Cluster ID",           "cluster.id"),
    Column("Cluster",    "Cluster Status",       "cluster.status"),

    Column("DBC",        "DBC Name",             "dbc.name"),
    Column("DBC",        "DBC ID",               "dbc.id"),
    Column("DBC",        "DBC CRN",              "dbc.crn"),
    Column("DBC",        "Status",               "dbc.status"),
    Column("DBC",        "Status Changed",       _date("dbc.statusChangedAt")),

    Column("Upgrade",    "Current Version",      "upgrade.upgradeVersions.currentVersion"),
    Column("Upgrade",    "Latest Version",       first("upgrade.latestVersion", "upgrade.upgradeVersions.latestVersion")),
    Column("Upgrade",    "Compatible Version",   "upgrade.compatibleVersion"),
]


# -------------------------------------------------------------------------
# CDW_VW — Virtual Warehouses
# -------------------------------------------------------------------------
CDW_VW: List[Column] = [
    Column("Cluster",    "Cluster Name",         "cluster.name"),
    Column("Cluster",    "Cluster ID",           "cluster.id"),

    Column("VW",         "VW Name",              "vw.name"),
    Column("VW",         "VW ID",                "vw.id"),
    Column("VW",         "VW CRN",               "vw.crn"),
    Column("VW",         "VW Type",              "vw.vwType"),
    Column("VW",         "Status",               "vw.status"),
    Column("VW",         "DBC ID",               "vw.dbcId"),
    Column("VW",         "CDH Version",          "vw.cdhVersion"),
    Column("VW",         "Instance Type",        "vw.instanceType"),
    Column("VW",         "Num Cores",            "vw.numOfCores"),
    Column("VW",         "Memory (MB)",          "vw.memoryCapacity"),
    Column("VW",         "Availability Zone",    "vw.availabilityZone"),
    Column("VW",         "Created",              _date("vw.creationDate")),
    Column("VW",         "Hue Endpoint",         "vw.endpoints.hue"),

    Column("Upgrade",    "Latest Version",       first("upgrade.latestVersion", "upgrade.upgradeVersions.latestVersion")),
    Column("Upgrade",    "Compatible Version",   "upgrade.compatibleVersion"),
]


# -------------------------------------------------------------------------
# CDW_DVIZ — Data Visualizations
# -------------------------------------------------------------------------
CDW_DVIZ: List[Column] = [
    Column("Cluster",    "Cluster Name",         "cluster.name"),
    Column("Cluster",    "Cluster ID",           "cluster.id"),

    Column("Data Viz",   "Name",                 "dviz.name"),
    Column("Data Viz",   "ID",                   "dviz.id"),
    Column("Data Viz",   "Status",               "dviz.status"),
    Column("Data Viz",   "Image Version",        "dviz.imageVersion"),
    Column("Data Viz",   "Size",                 "dviz.size"),
    Column("Data Viz",   "Creator CRN",          "dviz.creatorCrn"),
    Column("Data Viz",   "User Groups",          _join("dviz.userGroups")),
    Column("Data Viz",   "Admin Groups",         _join("dviz.adminGroups")),
]


# -------------------------------------------------------------------------
# CDW_HUE — Hue instances
# -------------------------------------------------------------------------
CDW_HUE: List[Column] = [
    Column("Cluster",    "Cluster Name",         "cluster.name"),
    Column("Cluster",    "Cluster ID",           "cluster.id"),

    Column("Hue",        "Name",                 first("hue.name", "hue.hueName")),
    Column("Hue",        "ID",                   first("hue.id", "hue.hueId")),
    Column("Hue",        "Status",               "hue.status"),
    Column("Hue",        "URL",                  first("hue.url", "hue.hueUrl")),
]


# -------------------------------------------------------------------------
# CDE — one row per CDE service (upgrade sidecar)
# -------------------------------------------------------------------------
CDE: List[Column] = [
    Column("Service",    "Service Name",         "service.name"),
    Column("Service",    "Cluster ID",           "service.clusterId"),
    Column("Service",    "Environment Name",     "service.environmentName"),
    Column("Service",    "Environment CRN",        "service.environmentCrn"),
    Column("Service",    "Account ID",           _crn_account("service.environmentCrn")),
    Column("Service",    "Status",               "service.status"),
    Column("Service",    "Cloud Platform",       "service.cloudPlatform"),
    Column("Service",    "Cluster FQDN",         "service.clusterFqdn"),
    Column("Service",    "Enabling Time",        _date("service.enablingTime")),
    Column("Service",    "Creator Email",        "service.creatorEmail"),
    Column("Service",    "Creator CRN",          "service.creatorCrn"),
    Column("Service",    "Instance Type",        "service.resources.instance_type"),
    Column("Service",    "Min Instances",        "service.resources.min_instances"),
    Column("Service",    "Max Instances",        "service.resources.max_instances"),
    Column("Service",    "Initial Instances",    "service.resources.initial_instances"),
    Column("Service",    "Root Volume (GB)",     "service.resources.root_vol_size"),
    Column("Service",    "Data Lake FS",         "service.dataLakeFileSystems"),
    Column("Service",    "Log Location",         "service.logLocation"),
    Column("Service",    "Backup Location",      "service.backupLocation"),
    Column("Service",    "Public Endpoint",      "service.publicEndpointEnabled"),
    Column("Service",    "Private Cluster",      "service.privateClusterEnabled"),
    Column("Service",    "SSD Used",             "service.ssdUsed"),

    # Requires CDP CLI >= 0.9.164; older CLIs drop service.version
    Column("Upgrade",    "Current Version",      "service.version"),
    Column("Upgrade",    "Previous Version Deployed", "service.previousVersionDeployed"),
    Column("Upgrade",    "Upgrade Message",      first(
        "upgrade.upgradeStatusMessage", "upgrade.upgradeStatus.upgradeStatusMessage"
    )),
    Column("Upgrade",    "Upgrade Next Step",    "upgrade.nextStep"),
    Column("Upgrade",    "All Steps Completed",  first(
        "upgrade.allStepsCompleted", "upgrade.upgradeStatus.allStepsCompleted"
    )),
]


# -------------------------------------------------------------------------
# CDE_VC — virtual clusters (service context repeated)
# -------------------------------------------------------------------------
CDE_VC: List[Column] = [
    Column("Service",    "Service Name",         "service.name"),
    Column("Service",    "Cluster ID",           "service.clusterId"),
    Column("Service",    "Environment Name",     "service.environmentName"),
    Column("Service",    "Status",               "service.status"),
    Column("Service",    "Service Version",      "service.version"),

    Column("Upgrade",    "Upgrade Message",      "upgrade.upgradeStatusMessage"),

    Column("Virtual Cluster", "VC Name",         "vc.vcName"),
    Column("Virtual Cluster", "VC ID",           "vc.vcId"),
    Column("Virtual Cluster", "Status",          "vc.status"),
    Column("Virtual Cluster", "VC Tier",         "vc.vcTier"),
    Column("Virtual Cluster", "Spark Version",   "vc.sparkVersion"),
    Column("Virtual Cluster", "Spark OS",        "vc.sparkOSName"),
    Column("Virtual Cluster", "Creation Time",   _date("vc.creationTime")),
    Column("Virtual Cluster", "CPU Requests",    "vc.resources.cpuRequests"),
    Column("Virtual Cluster", "Memory Requests", "vc.resources.memRequests"),
    Column("Virtual Cluster", "VC API URL",      "vc.vcApiUrl"),
    Column("Virtual Cluster", "VC UI URL",       "vc.VcUiUrl"),
    Column("Virtual Cluster", "History Server",  "vc.historyServerUrl"),
    Column("Virtual Cluster", "Livy URL",        "vc.livyServerUrl"),
    Column("Virtual Cluster", "Creator Email",   "vc.creatorEmail"),
]


# -------------------------------------------------------------------------
# CDE_BACKUPS — service backups
# -------------------------------------------------------------------------
CDE_BACKUPS: List[Column] = [
    Column("Service",    "Service Name",         "service.name"),
    Column("Service",    "Cluster ID",           "service.clusterId"),
    Column("Backup",     "Backup ID",            first("backup.backupId", "backup.id")),
    Column("Backup",     "Backup Name",          first("backup.backupName", "backup.name")),
    Column("Backup",     "Status",               "backup.status"),
    Column("Backup",     "Created",              lambda r: parse_iso_date(
        (r.get("backup") or {}).get("createdAt") or (r.get("backup") or {}).get("creationTime")
    )),
    Column("Backup",     "Location",             first("backup.location", "backup.backupLocation")),
]


# -------------------------------------------------------------------------
# CDF sheet (one row per deployment, with service context repeated)
# -------------------------------------------------------------------------
def _deployment_status_state():
    inner = at("deployment.status")
    return lambda rec: (
        inner(rec).get("state")
        if isinstance(inner(rec), dict)
        else inner(rec)
    )


CDF: List[Column] = [
    Column("Service",    "Service Name",         "service.name"),
    Column("Service",    "Service CRN",          "service.crn"),
    Column("Service",    "Environment CRN",      "service.environmentCrn"),
    Column("Service",    "Account ID",           _crn_account("service.environmentCrn")),
    Column("Service",    "Cluster ID",           "service.clusterId"),
    Column("Service",    "Workload Version",     first("service.workloadVersion", "service.version")),
    Column("Service",    "Status",               "service.status"),
    Column("Service",    "Cloud Platform",       "service.cloudPlatform"),
    Column("Service",    "Deployment Count",     "service.deploymentCount"),
    Column("Service",    "Min Nodes",            "service.minNodes"),
    Column("Service",    "Max Nodes",            "service.maxNodes"),
    Column("Service",    "Creator CRN",          "service.creatorCrn"),

    Column("Deployment", "Deployment Name",      "deployment.name"),
    Column("Deployment", "Deployment CRN",       "deployment.crn"),
    Column("Deployment", "Status",               _deployment_status_state()),
    Column("Deployment", "CFM NiFi Version",     first("deployment.cfmNifiVersion", "deployment.nifiVersion")),
    Column("Deployment", "Cluster Size",         "deployment.clusterSize"),
    Column("Deployment", "Current Node Count",   "deployment.currentNodeCount"),
    Column("Deployment", "Static Node Count",      "deployment.staticNodeCount"),
    Column("Deployment", "Autoscaling Enabled",  "deployment.autoscalingEnabled"),
    Column("Deployment", "Autoscale Min Nodes",  "deployment.autoscaleMinNodes"),
    Column("Deployment", "Autoscale Max Nodes",  "deployment.autoscaleMaxNodes"),
    Column("Deployment", "Flow Name",              first("deployment.flowName", "deployment.deployedFlow.artifactName")),
    Column("Deployment", "Flow Version",           "deployment.flowVersion"),
    Column("Deployment", "Project Name",           "deployment.project.name"),
    Column("Deployment", "Deployed By",            "deployment.deployedByName"),
    Column("Deployment", "Last Updated By",        "deployment.lastUpdatedByName"),
    Column("Deployment", "Updated",                "deployment.updated"),
    Column("Deployment", "NiFi URL",               "deployment.nifiUrl"),
    Column("Deployment", "DFX Local URL",          "deployment.dfxLocalUrl"),
    Column("Deployment", "Active Error Alerts",    "deployment.activeErrorAlertCount"),
    Column("Deployment", "Active Warning Alerts",  "deployment.activeWarningAlertCount"),
]


# -------------------------------------------------------------------------
# CDF_FLOWS — flow definitions
# -------------------------------------------------------------------------
CDF_FLOWS: List[Column] = [
    Column("Service",    "Service Name",         "service.name"),
    Column("Service",    "Service CRN",          "service.crn"),
    Column("Flow",       "Flow Name",            first("flow.name", "flow.flowName")),
    Column("Flow",       "Flow CRN",             first("flow.crn", "flow.flowCrn")),
    Column("Flow",       "Description",          "flow.description"),
    Column("Flow",       "Created",              lambda r: parse_iso_date(
        (r.get("flow") or {}).get("created") or (r.get("flow") or {}).get("createdTime")
    )),
    Column("Flow",       "Updated",              lambda r: parse_iso_date(
        (r.get("flow") or {}).get("updated") or (r.get("flow") or {}).get("updatedTime")
    )),
]


# -------------------------------------------------------------------------
# CDF_PROJECTS — DataFlow projects
# -------------------------------------------------------------------------
CDF_PROJECTS: List[Column] = [
    Column("Service",    "Service Name",         first("service.name", "project.service.name")),
    Column("Service",    "Service CRN",          first("service.crn", "project.service.crn")),
    Column("Project",    "Project Name",         "project.name"),
    Column("Project",    "Project CRN",          "project.crn"),
    Column("Project",    "Revision",             "project.revision"),
    Column("Project",    "Deleting",             "project.deleting"),
    Column("Project",    "Created",              _date("project.created")),
    Column("Project",    "Updated",              _date("project.updated")),
]


# -------------------------------------------------------------------------
# CDF_READYFLOWS — account-level ReadyFlow templates
# -------------------------------------------------------------------------
CDF_READYFLOWS: List[Column] = [
    Column("ReadyFlow",  "Name",                 first("readyflow.name", "readyflow.readyflowName")),
    Column("ReadyFlow",  "CRN",                  first("readyflow.readyflowCrn", "readyflow.crn")),
    Column("ReadyFlow",  "Summary",              "readyflow.summary"),
    Column("ReadyFlow",  "Source",               "readyflow.source"),
    Column("ReadyFlow",  "Destination",          "readyflow.destination"),
    Column("ReadyFlow",  "Latest Version",       "readyflow.latestVersion"),
    Column("ReadyFlow",  "Imported",             "readyflow.imported"),
]


# -------------------------------------------------------------------------
# CDF_DEPLOYMENT_EVENTS — deployment event history
# -------------------------------------------------------------------------
CDF_DEPLOYMENT_EVENTS: List[Column] = [
    Column("Deployment", "Deployment Name",      "deployment.name"),
    Column("Deployment", "Deployment CRN",       "deployment.crn"),
    Column("Deployment", "Status",               "deployment.status.state"),
    Column("Event",      "Event Name",           "item.name"),
    Column("Event",      "Event CRN",            "item.crn"),
    Column("Event",      "Severity",             "item.severity"),
    Column("Event",      "Event Type",           "item.eventType"),
    Column("Event",      "Alert Type",           "item.alertType"),
    Column("Event",      "First Occurrence",     _date("item.firstOccurrence")),
]


# -------------------------------------------------------------------------
# CDF_DEPLOYMENT_ALERTS — active deployment alerts
# -------------------------------------------------------------------------
CDF_DEPLOYMENT_ALERTS: List[Column] = [
    Column("Deployment", "Deployment Name",      "deployment.name"),
    Column("Deployment", "Deployment CRN",       "deployment.crn"),
    Column("Deployment", "Status",               "deployment.status.state"),
    Column("Alert",      "Alert Name",           "item.name"),
    Column("Alert",      "Alert CRN",            "item.crn"),
    Column("Alert",      "Severity",             "item.severity"),
    Column("Alert",      "Event Type",           "item.eventType"),
    Column("Alert",      "Alert Type",           "item.alertType"),
    Column("Alert",      "First Occurrence",     _date("item.firstOccurrence")),
]


# -------------------------------------------------------------------------
# COD sheet (one row per instance, with database context)
# -------------------------------------------------------------------------
COD: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Environment", "Environment CRN",        "environment.crn"),

    Column("Database",   "Database Name",          "database.databaseName"),
    Column("Database",   "Internal Name",          "database.internalName"),
    Column("Database",   "Backing DataHub Cluster", "cluster.clusterName"),
    Column("Database",   "Backing DataHub CRN",    "cluster.crn"),
    Column("Database",   "Database CRN",           "database.crn"),
    Column("Database",   "Environment Name",       "database.environmentName"),
    Column("Database",   "Environment CRN",        "database.environmentCrn"),
    Column("Database",   "Account ID",             _crn_account("database.environmentCrn")),
    Column("Database",   "Status",                 "database.status"),
    Column("Database",   "DB Version",             "database.dbVersion"),
    Column("Database",   "Architecture",           "database.architecture"),
    Column("Database",   "Creation Date",          _date("database.creationDate")),
    Column("Database",   "Creator CRN",            "database.creatorCrn"),
    Column("Database",   "Storage Location",       "database.storageLocation"),
    Column("Database",   "Hue Endpoint",           "database.hueEndpoint"),
    Column("Database",   "Gateway Nodes",          "database.gatewayNodesCount"),
    Column("Database",   "REST Worker Nodes",      "database.restworkerNodesCount"),
    Column("Database",   "Cloud Platform",         "database.cloudPlatform"),

    Column("Instance Group", "Group Name",         "group.name"),
    Column("Instance Group", "Group Recipes",      _join("group.recipes")),
    Column("Instance Group", "Subnet IDs",         _join("group.subnetIds")),
    Column("Instance Group", "Availability Zones", _join("group.availabilityZones")),

    Column("Instance",   "Instance ID",            "instance.id"),
    Column("Instance",   "FQDN",                   "instance.fqdn"),
    Column("Instance",   "State",                  "instance.state"),
    Column("Instance",   "Service Status",         "instance.status"),
    Column("Instance",   "Status Reason",          "instance.statusReason"),
    Column("Instance",   "Instance Group",         "instance.instanceGroup"),
    Column("Instance",   "Instance Role",          "instance.instanceType"),
    Column("Instance",   "VM Type",                "instance.instanceVmType"),
    Column("Instance",   "Private IP",             "instance.privateIp"),
    Column("Instance",   "Public IP",              "instance.publicIp"),
    Column("Instance",   "Availability Zone",      "instance.availabilityZone"),
    Column("Instance",   "Subnet ID",              "instance.subnetId"),
    Column("Instance",   "Attached Volumes",       "instance.attachedVolumes"),
]


# -------------------------------------------------------------------------
# COD_OPDB — OPDB sidecars (upgrade, connectivity, snapshots)
# -------------------------------------------------------------------------
def _connector_count(rec):
    connectors = at("connectivity.connectors")(rec) or []
    return len(connectors) if isinstance(connectors, list) else 0


COD_OPDB: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Database",   "Database Name",          "database.databaseName"),
    Column("Database",   "Internal Name",          "database.internalName"),
    Column("Database",   "Status",                 "database.status"),
    Column("Database",   "DB Version",             "database.dbVersion"),

    Column("Upgrade",    "Upgrade Status Reason",  "upgrade.statusReason"),
    Column("Upgrade",    "Runtime Upgrade Available", "upgrade.isRuntimeUpgradeAvailable"),
    Column("Upgrade",    "OS Upgrade Available",   "upgrade.isOSUpgradeAvailable"),
    Column("Upgrade",    "Current CDP Version",    "upgrade.currentComponentVersion.cdp"),
    Column("Upgrade",    "Current CM Version",     "upgrade.currentComponentVersion.cm"),

    Column("Connectivity", "Connector Count",      _connector_count),
    Column("Snapshots",  "Snapshot Count",       "snapshotCount"),
    Column("Restore",    "Restore Snapshot Count", "restoreSnapshotCount"),
    Column("Diagnostics", "Diagnostics Count",   "diagnosticsCount"),
]


# -------------------------------------------------------------------------
# COD_DATAHUB_HEALTH — CM service health on backing DataHub cluster
# -------------------------------------------------------------------------
COD_DATAHUB_HEALTH: List[Column] = [
    Column("Environment", "Environment Name",     "environment.environmentName"),
    Column("Database",   "Database Name",          "database.databaseName"),
    Column("Database",   "Internal Name",          "database.internalName"),

    Column("Cluster",     "Cluster Name",         "cluster.clusterName"),
    Column("Cluster",     "Cluster CRN",          "cluster.crn"),
    Column("Cluster",     "Status",               "cluster.status"),

    Column("Service",     "Service Type",         "service.type"),
    Column("Service",     "State",                "service.state"),
    Column("Service",     "Health Summary",       "service.healthSummary"),
    Column("Service",     "Health Checks",        _health_checks()),
]


# -------------------------------------------------------------------------
# Tier 2 — IAM
# -------------------------------------------------------------------------
IAM_USERS: List[Column] = [
    Column("User",       "User ID",              first("user.userId", "user.crn")),
    Column("User",       "Email",                first("user.email", "user.workloadUsername")),
    Column("User",       "First Name",           "user.firstName"),
    Column("User",       "Last Name",            "user.lastName"),
    Column("User",       "Status",               "user.status"),
    Column("User",       "Created",              _date("user.creationDate")),
]

IAM_GROUPS: List[Column] = [
    Column("Group",      "Group Name",           first("group.groupName", "group.name")),
    Column("Group",      "CRN",                  "group.crn"),
    Column("Group",      "Description",          "group.description"),
    Column("Group",      "Created",              _date("group.creationDate")),
]

IAM_ROLES: List[Column] = [
    Column("Role",       "Role Name",            first("role.roleName", "role.name")),
    Column("Role",       "CRN",                  "role.crn"),
    Column("Role",       "Description",          "role.description"),
]

IAM_RESOURCE_ROLES: List[Column] = [
    Column("Resource Role", "Role Name",         first("resourceRole.roleName", "resourceRole.resourceRoleName")),
    Column("Resource Role", "CRN",             "resourceRole.crn"),
    Column("Resource Role", "Description",       "resourceRole.description"),
]

IAM_MACHINE_USERS: List[Column] = [
    Column("Machine User", "Name",               first("machineUser.machineUserName", "machineUser.name")),
    Column("Machine User", "CRN",                "machineUser.crn"),
    Column("Machine User", "Status",             "machineUser.status"),
]

IAM_ENV_ASSIGNEES: List[Column] = [
    Column("Assignee",   "Type",                 "assignee.assigneeType"),
    Column("Assignee",   "CRN",                  "assignee.assigneeCrn"),
    Column("Assignee",   "Resource Role CRN",    "assignee.resourceRoleCrn"),
    Column("Assignee",   "Resource Role Name",   "assignee.resourceRoleName"),
]

# -------------------------------------------------------------------------
# Tier 2 — Audit
# -------------------------------------------------------------------------
AUDIT_ARCHIVE_RUNS: List[Column] = [
    Column("Run",        "Run ID",               first("run.runId", "run.id")),
    Column("Run",        "Status",               "run.status"),
    Column("Run",        "Start Time",           _date("run.startTime")),
    Column("Run",        "End Time",             _date("run.endTime")),
    Column("Run",        "Events Archived",      "run.eventsArchived"),
]

AUDIT_OUTSTANDING_BATCHES: List[Column] = [
    Column("Batch",      "Batch ID",             first("batch.batchId", "batch.id")),
    Column("Batch",      "Status",               "batch.status"),
    Column("Batch",      "Created",              _date("batch.creationTime")),
    Column("Batch",      "Event Count",          "batch.eventCount"),
]

# -------------------------------------------------------------------------
# Tier 2 — Replication Manager
# -------------------------------------------------------------------------
RM_POLICIES: List[Column] = [
    Column("Policy",     "Policy Name",          first("policy.name", "policy.policyName")),
    Column("Policy",     "Policy ID",          first("policy.id", "policy.policyId")),
    Column("Policy",     "Status",               "policy.status"),
    Column("Policy",     "Source Cluster",     first("policy.sourceClusterName", "policy.sourceClusterCrn")),
    Column("Policy",     "Target Cluster",     first("policy.targetClusterName", "policy.targetClusterCrn")),
]

RM_CLUSTERS: List[Column] = [
    Column("Cluster",    "Name",                 "cluster.name"),
    Column("Cluster",    "CRN",                  "cluster.crn"),
    Column("Cluster",    "Type",                 "cluster.clusterType"),
    Column("Cluster",    "Environment CRN",      "cluster.environmentCrn"),
    Column("Cluster",    "Stack Version",        "cluster.stackVersion"),
    Column("Cluster",    "Total Hosts",        "cluster.totalHosts"),
]

RM_PAIRED_HBASE: List[Column] = [
    Column("Cluster",    "Name",                 first("cluster.name", "cluster.clusterName")),
    Column("Cluster",    "CRN",                  "cluster.crn"),
    Column("Cluster",    "URL",                  first("cluster.clusterUrl", "cluster.url")),
    Column("Cluster",    "Status",               "cluster.status"),
]

# -------------------------------------------------------------------------
# Tier 2 — Lakehouse Optimizer
# -------------------------------------------------------------------------
LHO_POLICIES: List[Column] = [
    Column("Data Hub",   "Cluster Name",         "datahub.clusterName"),
    Column("Policy",     "Policy Name",          "policy.policyName"),
    Column("Policy",     "Status",               "policy.status"),
    Column("Policy",     "Table Count",          "policy.tableCount"),
    Column("Policy",     "Task Count",           "policy.taskCount"),
    Column("Policy",     "Is Default",           "policy.isDefault"),
    Column("Policy",     "Last Execution",       _date("policy.lastExecutionTime")),
]

LHO_HEALTH: List[Column] = [
    Column("Data Hub",   "Cluster Name",         "datahub.clusterName"),
    Column("Health",     "Status",               first("health.status", "health.healthStatus")),
    Column("Health",     "Message",              first("health.message", "health.statusMessage")),
]


# -------------------------------------------------------------------------
# Tier 3 — Data Catalog, dfworkload, deep diagnostics metadata
# -------------------------------------------------------------------------
DATACATALOG_SHARES: List[Column] = [
    Column("Share",      "Share ID",             first("share.dataShareId", "share.id", "share.name")),
    Column("Share",      "Name",                 first("share.name", "share.dataShareName")),
    Column("Share",      "Status",               "share.status"),
    Column("Share",      "Created",              _date("share.creationDate")),
]

DATACATALOG_EXTERNAL_USERS: List[Column] = [
    Column("User",       "Email",                first("user.email", "user.userEmail")),
    Column("User",       "Name",                 first("user.name", "user.displayName")),
    Column("User",       "Status",               "user.status"),
]

DFW_FLOW_DRAFTS: List[Column] = [
    Column("Draft",      "Name",                 first("draft.name", "draft.flowName")),
    Column("Draft",      "CRN",                  "draft.crn"),
    Column("Draft",      "Status",               "draft.status"),
    Column("Draft",      "Updated",              _date("draft.updated")),
]

DFW_DEPLOYMENTS: List[Column] = [
    Column("Deployment", "Name",                 "deployment.name"),
    Column("Config",     "NiFi Version",         first("config.nifiVersion", "config.deploymentConfiguration.nifiVersion")),
    Column("Config",     "Status",               first("config.status", "config.deploymentConfiguration.status")),
]

DATALAKE_BACKUPS: List[Column] = [
    Column("Environment", "Environment Name",    "environment.environmentName"),
    Column("Datalake",   "Datalake Name",        "datalake.datalakeName"),
    Column("Backup",     "Backup Name",          first("backup.backupName", "backup.name")),
    Column("Backup",     "Status",               "backup.status"),
    Column("Backup",     "Created",              _date("backup.created")),
]

DATAHUB_SCALING_ACTIVITIES: List[Column] = [
    Column("Environment", "Environment Name",    "environment.environmentName"),
    Column("Cluster",    "Cluster Name",         "cluster.clusterName"),
    Column("Activity",   "Activity ID",          first("activity.id", "activity.activityId")),
    Column("Activity",   "Status",               "activity.status"),
    Column("Activity",   "Start Time",           _date("activity.startTime")),
    Column("Activity",   "End Time",             _date("activity.endTime")),
]

# -------------------------------------------------------------------------
# Tier 4 — consumption, compute, platform APIs
# -------------------------------------------------------------------------
CONSUMPTION_USAGE: List[Column] = [
    Column("Usage",      "Environment CRN",      first("usageRecord.environmentCrn", "usageRecord.resourceCrn")),
    Column("Usage",      "Resource Type",        first("usageRecord.resourceType", "usageRecord.serviceType")),
    Column("Usage",      "Start Time",           _date("usageRecord.startTime")),
    Column("Usage",      "End Time",             _date("usageRecord.endTime")),
    Column("Usage",      "Amount",               first("usageRecord.amount", "usageRecord.usageAmount")),
]

COMPUTE_CLUSTERS: List[Column] = [
    Column("Cluster",    "Name",                 first("cluster.name", "cluster.clusterName")),
    Column("Cluster",    "CRN",                  "cluster.crn"),
    Column("Cluster",    "Status",               "cluster.status"),
    Column("Cluster",    "Created",              _date("cluster.creationDate")),
]

COMPUTE_DEPLOYMENTS: List[Column] = [
    Column("Deployment", "Name",                 first("deployment.name", "deployment.deploymentName")),
    Column("Deployment", "Namespace",            "deployment.namespace"),
    Column("Deployment", "Status",               "deployment.status"),
    Column("Deployment", "Created",              _date("deployment.creationDate")),
]

ENV_CREDENTIALS: List[Column] = [
    Column("Credential", "Name",                 first("credential.credentialName", "credential.name")),
    Column("Credential", "Cloud Platform",       first("credential.cloudPlatform", "credential.platform")),
    Column("Credential", "Description",          "credential.description"),
]

ENV_PROXY_CONFIGS: List[Column] = [
    Column("Proxy",      "Name",                 first("proxyConfig.proxyConfigName", "proxyConfig.name")),
    Column("Proxy",      "Host",                 first("proxyConfig.host", "proxyConfig.proxyHost")),
    Column("Proxy",      "Port",                 first("proxyConfig.port", "proxyConfig.proxyPort")),
]

DATAHUB_CLUSTER_DEFINITIONS: List[Column] = [
    Column("Definition", "Name",                 first("definition.clusterDefinitionName", "definition.name")),
    Column("Definition", "Type",                 first("definition.type", "definition.clusterType")),
    Column("Definition", "Status",               "definition.status"),
]

DATAHUB_SCALING_DETAILS: List[Column] = [
    Column("Environment", "Environment Name",    "environment.environmentName"),
    Column("Cluster",    "Cluster Name",         "cluster.clusterName"),
    Column("Detail",     "Operation ID",         first("detail.operationId", "detail.id")),
    Column("Detail",     "Status",               "detail.status"),
    Column("Detail",     "Message",              first("detail.message", "detail.statusMessage")),
]

CDW_EVENTS: List[Column] = [
    Column("Environment", "Environment Name",    "environment.environmentName"),
    Column("Cluster",    "Cluster Name",         "clusterName"),
    Column("Event",      "Type",                 first("event.eventType", "event.type")),
    Column("Event",      "Status",               "event.status"),
    Column("Event",      "Timestamp",            _date("event.timestamp")),
    Column("Event",      "Message",              first("event.message", "event.details")),
]

# -------------------------------------------------------------------------
# Tier 5 — diagnostic bundle jobs
# -------------------------------------------------------------------------
DIAGNOSTIC_JOB: List[Column] = [
    Column("Job",        "Operation ID",         first("job.operationId", "job.commandId", "job.jobId")),
    Column("Job",        "Status",               first("job.status", "job.operation.status")),
    Column("Job",        "Type",                 first("job.type", "job.operationType")),
    Column("Job",        "Created",              _date("job.startTime")),
]

DFW_REPORTING_TASKS: List[Column] = [
    Column("Task",       "Name",                 first("task.name", "task.taskName")),
    Column("Task",       "Type",                 first("task.type", "task.reportingTaskType")),
    Column("Task",       "State",                first("task.state", "task.status")),
]


SHEETS: List[Tuple[str, List[Column]]] = [
    ("ENVIRONMENT", ENVIRONMENT),
    ("FREEIPA",     FREEIPA),
    ("DATALAKE",    DATALAKE),
    ("DATALAKE_HEALTH", DATALAKE_HEALTH),
    ("DATALAKE_HOSTS", DATALAKE_HOSTS),
    ("DATAHUBS",    DATAHUBS),
    ("DATAHUB_HEALTH", DATAHUB_HEALTH),
    ("DATAHUB_HOSTS", DATAHUB_HOSTS),
    ("DATAHUB_AUTOSCALE_HISTORY", DATAHUB_AUTOSCALE_HISTORY),
    ("DATAHUB_LIFECYCLE", DATAHUB_LIFECYCLE),
    ("DATABASES",   DATABASES),
    ("CMLCAI",      CMLCAI),
    ("CAI_INSTANCES", CAI_INSTANCES),
    ("CAI_SERVING", CAI_SERVING),
    ("CAI_REGISTRY", CAI_REGISTRY),
    ("CAI_SERVING_ACCESS", CAI_SERVING_ACCESS),
    ("CAI_REGISTRY_ACCESS", CAI_REGISTRY_ACCESS),
    ("CDW",         CDW),
    ("CDW_DBC",     CDW_DBC),
    ("CDW_VW",      CDW_VW),
    ("CDW_DVIZ",    CDW_DVIZ),
    ("CDW_HUE",     CDW_HUE),
    ("CDE",         CDE),
    ("CDE_VC",      CDE_VC),
    ("CDE_BACKUPS", CDE_BACKUPS),
    ("CDF",         CDF),
    ("CDF_FLOWS",   CDF_FLOWS),
    ("CDF_PROJECTS", CDF_PROJECTS),
    ("CDF_READYFLOWS", CDF_READYFLOWS),
    ("CDF_DEPLOYMENT_EVENTS", CDF_DEPLOYMENT_EVENTS),
    ("CDF_DEPLOYMENT_ALERTS", CDF_DEPLOYMENT_ALERTS),
    ("COD",         COD),
    ("COD_OPDB",    COD_OPDB),
    ("COD_DATAHUB_HEALTH", COD_DATAHUB_HEALTH),
    ("IAM_USERS", IAM_USERS),
    ("IAM_GROUPS", IAM_GROUPS),
    ("IAM_ROLES", IAM_ROLES),
    ("IAM_RESOURCE_ROLES", IAM_RESOURCE_ROLES),
    ("IAM_MACHINE_USERS", IAM_MACHINE_USERS),
    ("IAM_ENV_ASSIGNEES", IAM_ENV_ASSIGNEES),
    ("AUDIT_ARCHIVE_RUNS", AUDIT_ARCHIVE_RUNS),
    ("AUDIT_OUTSTANDING_BATCHES", AUDIT_OUTSTANDING_BATCHES),
    ("RM_POLICIES", RM_POLICIES),
    ("RM_CLUSTERS", RM_CLUSTERS),
    ("RM_PAIRED_HBASE", RM_PAIRED_HBASE),
    ("LHO_POLICIES", LHO_POLICIES),
    ("LHO_HEALTH", LHO_HEALTH),
    ("DATACATALOG_SHARES", DATACATALOG_SHARES),
    ("DATACATALOG_EXTERNAL_USERS", DATACATALOG_EXTERNAL_USERS),
    ("DFW_FLOW_DRAFTS", DFW_FLOW_DRAFTS),
    ("DFW_DEPLOYMENTS", DFW_DEPLOYMENTS),
    ("DATALAKE_BACKUPS", DATALAKE_BACKUPS),
    ("DATAHUB_SCALING_ACTIVITIES", DATAHUB_SCALING_ACTIVITIES),
    ("CONSUMPTION_USAGE", CONSUMPTION_USAGE),
    ("COMPUTE_CLUSTERS", COMPUTE_CLUSTERS),
    ("COMPUTE_DEPLOYMENTS", COMPUTE_DEPLOYMENTS),
    ("ENV_CREDENTIALS", ENV_CREDENTIALS),
    ("ENV_PROXY_CONFIGS", ENV_PROXY_CONFIGS),
    ("DATAHUB_CLUSTER_DEFINITIONS", DATAHUB_CLUSTER_DEFINITIONS),
    ("DATAHUB_SCALING_DETAILS", DATAHUB_SCALING_DETAILS),
    ("CDW_EVENTS", CDW_EVENTS),
    ("FREEIPA_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("DATALAKE_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("DATAHUB_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("CDW_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("COD_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("RM_DIAGNOSTIC_JOBS", DIAGNOSTIC_JOB),
    ("DFW_REPORTING_TASKS", DFW_REPORTING_TASKS),
]
