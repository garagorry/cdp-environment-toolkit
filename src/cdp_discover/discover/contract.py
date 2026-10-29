#!/usr/bin/env python3
"""Check client.py CLI calls against the installed CDP CLI model (offline).

Every ``self.execute("<service>", "<operation>", flag=value, ...)`` call in
client.py is checked for: the operation exists, each flag maps to a request
property, and every required property is passed.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from cdp_discover.discover.cli_model import kebab_to_camel

CLIENT_PATH = Path(__file__).with_name("client.py")

# Keyword arguments consumed by CDPClient.execute itself or global CLI options
_NON_API_KWARGS = {"task_name", "no_paginate", "max_items", "starting_token", "page_size"}


@dataclass
class ContractIssue:
    method: str
    line: int
    service: str
    operation: str
    problem: str

    def __str__(self) -> str:
        return f"client.py:{self.line} {self.method}: cdp {self.service} {self.operation}: {self.problem}"


def model_param_to_flag(name: str) -> str:
    """Request property -> CLI flag name as cdpcli renders it (serviceID -> service-id)."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name).lower()


def _execute_calls(tree: ast.AST):
    """Yield (method_name, call) for each self.execute(...) call."""
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                and len(node.args) >= 2
                and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args[:2])
            ):
                yield func.name, node


def check_client_contract(
    model: Dict[str, Dict[str, dict]], client_source: Optional[str] = None
) -> List[ContractIssue]:
    """Return contract violations of client.py against a CLI model from load_cli_model()."""
    source = client_source if client_source is not None else CLIENT_PATH.read_text(encoding="utf-8")
    issues: List[ContractIssue] = []
    for method, call in _execute_calls(ast.parse(source)):
        service, operation = call.args[0].value, call.args[1].value

        def issue(problem: str) -> None:
            issues.append(ContractIssue(method, call.lineno, service, operation, problem))

        ops = model.get(service)
        if ops is None:
            issue("service not in CLI model")
            continue
        op = ops.get(kebab_to_camel(operation))
        if op is None:
            issue("operation not in CLI model")
            continue

        flags = {model_param_to_flag(p): p for p in op["params"]}
        passed = set()
        dynamic = False
        for kw in call.keywords:
            if kw.arg is None:  # **kwargs: flags decided at runtime
                dynamic = True
                continue
            if kw.arg in _NON_API_KWARGS:
                continue
            flag = kw.arg.replace("_", "-")
            if flag not in flags:
                issue(f"unknown flag --{flag} (accepted: {', '.join('--' + f for f in sorted(flags)) or 'none'})")
            else:
                passed.add(flags[flag])
        if not dynamic:
            for req in op["required"]:
                if req not in passed:
                    issue(f"missing required --{model_param_to_flag(req)}")
    return issues
