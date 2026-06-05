#!/usr/bin/env python3
"""Data Catalog discovery module (Tier 3 / deep)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class DataCatalogDiscovery:
    """Discover data shares and external users for an environment."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("📚 Starting Data Catalog discovery...")
        results = {"data_shares": [], "external_users": [], "success": False}
        dc_dir = self.config.get_service_dir("datacatalog")
        ts = self.config.timestamp

        env_crn, datalake_crn = self._environment_and_datalake_crns()
        if not env_crn:
            log("⚠️ Could not resolve environment CRN for Data Catalog")
            return results

        shares_json, shares_err = self.client.list_datacatalog_data_shares(
            env_crn, datalake_crn=datalake_crn
        )
        if shares_json:
            shares = shares_json.get("dataShares") or shares_json.get("shares") or []
            save_to_file(shares_json, dc_dir / f"dc_data_shares_{ts}.json")
            if shares:
                log(f"Found {len(shares)} data share(s)")
                self.exporter.save_instance_groups_to_csv(
                    dc_dir / f"dc_data_shares_{ts}.csv", shares
                )
            results["data_shares"] = shares
            self._describe_data_shares(shares, env_crn, datalake_crn, dc_dir, ts)
        elif self.config.debug:
            log(f"DEBUG: Data Catalog shares: {shares_err}")

        users_json, users_err = self.client.list_datacatalog_external_users(
            env_crn, datalake_crn=datalake_crn
        )
        if users_json:
            users = users_json.get("externalUsers") or users_json.get("users") or []
            save_to_file(users_json, dc_dir / f"dc_external_users_{ts}.json")
            if users:
                log(f"Found {len(users)} external user(s)")
                self.exporter.save_instance_groups_to_csv(
                    dc_dir / f"dc_external_users_{ts}.csv", users
                )
            results["external_users"] = users
        elif self.config.debug:
            log(f"DEBUG: Data Catalog external users: {users_err}")

        results["success"] = bool(results["data_shares"] or results["external_users"])
        if not results["success"]:
            log("ℹ️ No Data Catalog data collected (service may be unavailable)")
        return results

    def _describe_data_shares(self, shares, env_crn, datalake_crn, dc_dir, ts):
        shares_dir = dc_dir / "data_shares"
        shares_dir.mkdir(parents=True, exist_ok=True)
        for share in shares:
            share_id = share.get("dataShareId") or share.get("id") or share.get("name")
            if not share_id:
                continue
            detail, err = self.client.get_datacatalog_data_share(
                share_id, env_crn, datalake_crn=datalake_crn
            )
            if not detail:
                if self.config.debug:
                    log(f"DEBUG: data share {share_id}: {err}")
                continue
            safe_id = str(share_id).replace("/", "_")
            subdir = shares_dir / safe_id
            subdir.mkdir(parents=True, exist_ok=True)
            save_to_file(detail, subdir / f"data_share_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                detail, subdir / f"data_share_{ts}.csv"
            )

    def _environment_and_datalake_crns(self):
        env_json, _ = self.client.describe_environment(self.config.environment_name)
        env_crn = None
        if env_json:
            env = env_json.get("environment") or env_json
            env_crn = env.get("crn")

        datalake_crn = None
        dl_json, _ = self.client.list_datalakes(self.config.environment_name)
        if dl_json:
            datalakes = dl_json.get("datalakes") or []
            if datalakes:
                datalake_crn = datalakes[0].get("crn")
        return env_crn, datalake_crn
