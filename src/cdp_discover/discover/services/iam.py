#!/usr/bin/env python3
"""IAM discovery module (account-level, env-scoped assignees)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class IAMDiscovery:
    """Discover IAM users, groups, roles, and environment resource assignees."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("🔐 Starting IAM discovery...")
        results = {"success": False}
        iam_dir = self.config.get_service_dir("iam")
        ts = self.config.timestamp

        account_json, account_err = self.client.get_iam_account()
        if account_json:
            save_to_file(account_json, iam_dir / f"iam_account_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                account_json, iam_dir / f"iam_account_{ts}.csv"
            )
            results["account"] = account_json
        elif self.config.debug:
            log(f"DEBUG: IAM account: {account_err}")

        list_calls = [
            ("users", self.client.list_iam_users, "users"),
            ("groups", self.client.list_iam_groups, "groups"),
            ("roles", self.client.list_iam_roles, "roles"),
            ("resource_roles", self.client.list_iam_resource_roles, "resourceRoles"),
            ("machine_users", self.client.list_iam_machine_users, "machineUsers"),
        ]
        any_data = bool(account_json)
        for key, method, list_key in list_calls:
            data, err = method()
            if data:
                any_data = True
                save_to_file(data, iam_dir / f"iam_{key}_{ts}.json")
                items = data.get(list_key) or []
                if items:
                    log(f"Found {len(items)} IAM {key.replace('_', ' ')}")
                    self.exporter.save_instance_groups_to_csv(
                        iam_dir / f"iam_{key}_{ts}.csv", items
                    )
                results[key] = data
            elif self.config.debug:
                log(f"DEBUG: IAM {key}: {err}")

        env_crn = self._environment_crn()
        if env_crn:
            assignees_json, assignees_err = self.client.list_iam_resource_assignees(env_crn)
            if assignees_json:
                any_data = True
                save_to_file(
                    assignees_json,
                    iam_dir / f"iam_env_resource_assignees_{ts}.json",
                )
                assignees = assignees_json.get("resourceAssignees") or assignees_json.get("assignees") or []
                if assignees:
                    log(f"Found {len(assignees)} IAM assignee(s) for environment")
                    self.exporter.save_instance_groups_to_csv(
                        iam_dir / f"iam_env_resource_assignees_{ts}.csv",
                        assignees,
                    )
                results["env_resource_assignees"] = assignees_json
            elif self.config.debug:
                log(f"DEBUG: IAM env resource assignees: {assignees_err}")

        results["success"] = any_data
        if not any_data:
            log("ℹ️ No IAM data collected (service may be unavailable)")
        return results

    def _environment_crn(self):
        env_json, _ = self.client.describe_environment(self.config.environment_name)
        if not env_json:
            return None
        env = env_json.get("environment") or env_json
        return env.get("crn")
