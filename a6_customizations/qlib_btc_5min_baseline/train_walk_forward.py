import argparse
import json
import os
import sys
from pathlib import Path

SYSTEM_LIBSTDCXX = "/usr/lib/x86_64-linux-gnu/libstdc++.so.6"


def _ensure_lightgbm_runtime():
    """Re-exec the process with the system libstdc++ preloaded.

    The current conda environment ships an older libstdc++.so.6 which misses
    GLIBCXX_3.4.30, while the system copy provides it. LightGBM needs that
    newer symbol to load successfully.
    """

    if not sys.platform.startswith("linux"):
        return
    if not os.path.exists(SYSTEM_LIBSTDCXX):
        return

    ld_preload = os.environ.get("LD_PRELOAD", "")
    preload_items = [item for item in ld_preload.split(":") if item]
    if SYSTEM_LIBSTDCXX in preload_items:
        return

    os.environ["LD_PRELOAD"] = ":".join([SYSTEM_LIBSTDCXX] + preload_items)
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)


_ensure_lightgbm_runtime()

from experiment import BaselineConfig, run_walk_forward


def parse_args():
    parser = argparse.ArgumentParser(description="BTCUSDT 5-minute event contract baseline walk-forward training")
    parser.add_argument(
        "--provider-uri",
        default="a6_customizations/binance_data-qlib/qlib_data_1min",
        help="Qlib 1-minute data directory",
    )
    parser.add_argument("--model-type", default="lightgbm", choices=["auto", "lightgbm", "xgboost"])
    parser.add_argument("--instrument", default="BTCUSDT")
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--valid-days", type=int, default=7)
    parser.add_argument("--test-days", type=int, default=7)
    parser.add_argument("--retrain-days", type=int, default=7)
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--threshold-start", type=float, default=0.55)
    parser.add_argument("--threshold-end", type=float, default=0.80)
    parser.add_argument("--threshold-step", type=float, default=0.01)
    parser.add_argument("--experiment-start", default=None, help="Optional rolling experiment start time")
    parser.add_argument("--experiment-end", default=None, help="Optional rolling experiment end time")
    parser.add_argument(
        "--output-dir",
        default="a6_customizations/qlib_btc_5min_baseline/outputs/latest",
        help="Directory to save metrics and trade logs",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    config = BaselineConfig(
        provider_uri=args.provider_uri,
        model_type=args.model_type,
        instrument=args.instrument,
        train_days=args.train_days,
        valid_days=args.valid_days,
        test_days=args.test_days,
        retrain_days=args.retrain_days,
        sample_minutes=args.sample_minutes,
        threshold_start=args.threshold_start,
        threshold_end=args.threshold_end,
        threshold_step=args.threshold_step,
        experiment_start=args.experiment_start,
        experiment_end=args.experiment_end,
        output_dir=str(output_dir),
    )
    summary = run_walk_forward(config)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
