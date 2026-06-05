#!/usr/bin/env python3
"""JSON exporter for CDP discovery data."""

import json
from pathlib import Path

from cdp_discover.discover.utils import log


class JSONExporter:
    """Export discovery data to JSON format."""

    def __init__(self, indent=2):
        self.indent = indent

    def save(self, data, filepath):
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=self.indent)

        log(f"✅ Saved JSON: {filepath}")

    def save_pretty(self, data, filepath):
        self.save(data, filepath)

    def save_compact(self, data, filepath):
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))

        log(f"✅ Saved compact JSON: {filepath}")
