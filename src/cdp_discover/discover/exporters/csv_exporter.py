#!/usr/bin/env python3
"""CSV exporter for CDP discovery data."""

import csv
from pathlib import Path

from cdp_discover.discover.utils import flatten_json, log


class CSVExporter:
    """Export discovery data to CSV format."""

    def __init__(self):
        pass

    def save_instance_groups_to_csv(self, csv_path, rows):
        if not rows:
            log(f"⚠️ No data to write: {csv_path}")
            return

        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        all_fieldnames = set()
        for row in rows:
            all_fieldnames.update(row.keys())
        all_fieldnames = sorted(all_fieldnames)

        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=all_fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        log(f"✅ Saved CSV: {csv_path}")

    def save_flattened_json_to_csv(self, json_obj, csv_path):
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(json_obj, list):
            flat_rows = [flatten_json(item) for item in json_obj]
        else:
            flat_rows = [flatten_json(json_obj)]

        if not flat_rows:
            log(f"⚠️ No data to write: {csv_path}")
            return

        fieldnames = set()
        for row in flat_rows:
            fieldnames.update(row.keys())
        fieldnames = sorted(fieldnames)

        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in flat_rows:
                writer.writerow(row)

        log(f"✅ Saved CSV: {csv_path}")

    def save_dict_list_to_csv(self, data, csv_path):
        if not data:
            log(f"⚠️ No data to write: {csv_path}")
            return

        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = set()
        for row in data:
            fieldnames.update(row.keys())
        fieldnames = sorted(fieldnames)

        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow(row)

        log(f"✅ Saved CSV: {csv_path}")
