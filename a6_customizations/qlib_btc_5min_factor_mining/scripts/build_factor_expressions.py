#!/usr/bin/env python3
"""
Build draft factor expression specs from a proposed factor plan.

This script does not run mining. It only renders a human-checkable spec so we
can confirm factor definitions and params before generating data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _render_factor_specs(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for factor in plan.get("factors", []):
        if not factor.get("enabled", True):
            continue
        specs.append(
            {
                "name": factor.get("name"),
                "family": factor.get("family"),
                "status": factor.get("status", "proposed"),
                "params": factor.get("params", {}),
                "rationale": factor.get("rationale", ""),
            }
        )
    return specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render draft factor specs from factor plan.")
    parser.add_argument("--plan", required=True, help="Path to factor plan yaml")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output json path. If omitted, print to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan_path = Path(args.plan).resolve()
    plan = _load_yaml(plan_path)
    specs = _render_factor_specs(plan)
    payload = {
        "plan_name": plan.get("meta", {}).get("plan_name"),
        "status": plan.get("meta", {}).get("status"),
        "target": plan.get("meta", {}).get("target", {}),
        "factor_specs": specs,
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved draft spec to: {output_path}")
        return

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
