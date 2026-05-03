#!/usr/bin/env python3
"""
Factor mining entrypoint with a confirmation gate.

Rules:
- mode=show-plan: display factor candidates and params.
- mode=mine: only allowed when meta.status in plan is confirmed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import yaml

from build_factor_expressions import _render_factor_specs
from factor_mining_pipeline import MiningConfig, run_mining


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run factor mining with confirmation gate")
    parser.add_argument("--plan", required=True, help="Path to factor plan yaml")
    parser.add_argument("--mode", choices=["show-plan", "mine"], default="show-plan")
    parser.add_argument(
        "--provider-uri",
        default="a6_customizations/binance_data-qlib/qlib_data_1min",
        help="Qlib data directory",
    )
    parser.add_argument(
        "--instrument",
        default="BTCUSDT",
        help="One symbol (e.g. BTCUSDT), comma list, or ALL",
    )
    parser.add_argument("--lookback-days", type=int, default=180, help="Use recent N days for first-pass mining")
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--entry-offset-minutes", type=int, default=1)
    parser.add_argument("--horizon-minutes", type=int, default=5)
    parser.add_argument("--eval-quantile", type=float, default=0.2)
    parser.add_argument("--min-samples-per-factor", type=int, default=500)
    parser.add_argument(
        "--output-dir",
        default="a6_customizations/qlib_btc_5min_factor_mining/outputs/latest",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan_path = Path(args.plan).resolve()
    plan = _load_yaml(plan_path)

    status = str(plan.get("meta", {}).get("status", "proposed")).strip().lower()
    factor_specs = _render_factor_specs(plan)
    payload = {
        "plan": str(plan_path),
        "status": status,
        "factor_count": len(factor_specs),
        "target": plan.get("meta", {}).get("target", {}),
        "objective": plan.get("meta", {}).get("objective", {}),
        "factors": factor_specs,
    }

    if args.mode == "show-plan":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if status != "confirmed":
        raise SystemExit(
            "plan is not confirmed. set meta.status=confirmed after reviewing factors/params/rationale."
        )

    summary = run_mining(
        MiningConfig(
            plan_path=str(plan_path),
            provider_uri=args.provider_uri,
            instrument=args.instrument,
            sample_minutes=args.sample_minutes,
            entry_offset_minutes=args.entry_offset_minutes,
            horizon_minutes=args.horizon_minutes,
            lookback_days=args.lookback_days,
            output_dir=args.output_dir,
            eval_quantile=args.eval_quantile,
            min_samples_per_factor=args.min_samples_per_factor,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
