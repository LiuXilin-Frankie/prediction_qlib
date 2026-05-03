#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import qlib
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
BASELINE_DIR = PROJECT_ROOT / "a6_customizations" / "qlib_btc_5min_baseline"
TS_VALIDATION_DIR = PROJECT_ROOT / "a6_customizations" / "qlib_ts_factor_validation_template" / "scripts"
for p in [str(BASELINE_DIR), str(TS_VALIDATION_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from data_handler import BTC5MinAlpha158  # noqa: E402
from validate_timeseries_factors import ValidationConfig, evaluate_factor  # noqa: E402

_QLIB_INITIALIZED = False


def init_qlib(provider_uri: str) -> None:
    global _QLIB_INITIALIZED
    if _QLIB_INITIALIZED:
        return
    qlib.init(provider_uri=str(Path(provider_uri).resolve()), expression_cache=None, dataset_cache=None)
    _QLIB_INITIALIZED = True


def parse_instruments(raw: str, all_inst: List[str]) -> List[str]:
    raw = raw.strip()
    if raw.lower() == "all":
        return sorted(all_inst)
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if not items:
        raise ValueError("instrument is empty")
    return items


def get_all_instruments(provider_uri: str) -> List[str]:
    inst_path = Path(provider_uri).resolve() / "instruments" / "all.txt"
    df = pd.read_csv(inst_path, sep="\t", header=None, names=["instrument", "start_time", "end_time"])
    return sorted(df["instrument"].astype(str).tolist())


def prepare_alpha158_panel(
    provider_uri: str,
    instruments: List[str],
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    sample_minutes: int,
) -> pd.DataFrame:
    init_qlib(provider_uri)
    panels: List[pd.DataFrame] = []
    for inst in instruments:
        handler = BTC5MinAlpha158(
            instruments=[inst],
            start_time=start_time,
            end_time=end_time + pd.Timedelta(minutes=6),
            fit_start_time=start_time,
            fit_end_time=end_time,
            freq="1min",
            entry_offset_minutes=1,
            horizon_minutes=5,
        )
        dataset = DatasetH(handler=handler, segments={"all": (start_time, end_time)})
        raw = dataset.prepare("all", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        if raw.empty:
            continue
        feat = raw["feature"].copy()
        lbl = raw["label"].iloc[:, 0].rename("future_return")
        df = feat.copy()
        df["future_return"] = lbl
        if isinstance(df.index, pd.MultiIndex):
            if "datetime" in df.index.names:
                dt = df.index.get_level_values("datetime")
            else:
                dt = df.index.get_level_values(-1)
        else:
            dt = df.index
        df = df.reset_index(drop=True)
        df["datetime"] = pd.to_datetime(dt).values
        sample_mask = (df["datetime"].dt.minute % sample_minutes == 0) & (df["datetime"].dt.second == 0)
        df = df.loc[sample_mask].copy()
        df["target"] = (df["future_return"] > 0.0).astype(int)
        df["instrument"] = inst
        df = df.dropna(subset=["future_return"]).reset_index(drop=True)

        rename_map = {c: f"alpha158__{c}" for c in df.columns if c not in {"instrument", "datetime", "future_return", "target"}}
        df = df.rename(columns=rename_map)
        panels.append(df)
    if not panels:
        return pd.DataFrame()
    return pd.concat(panels, ignore_index=True)


def evaluate_factor_panel(panel: pd.DataFrame, cfg: ValidationConfig) -> pd.DataFrame:
    reserved = {"instrument", "datetime", "future_return", "target"}
    factors = [c for c in panel.columns if c not in reserved]
    rows = []
    for f in factors:
        summary, _ = evaluate_factor(f, panel, cfg)
        if summary:
            rows.append(summary)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.sort_values(
        by=["edge_vs_break_even", "rolling_edge_p10", "auc_best", "samples"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return out


def run_compare(args: argparse.Namespace) -> Dict:
    custom_panel_path = Path(args.custom_factor_panel).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    custom = pd.read_parquet(custom_panel_path)
    if "instrument" not in custom.columns:
        custom["instrument"] = "BTCUSDT"
    custom["datetime"] = pd.to_datetime(custom["datetime"])

    all_inst = get_all_instruments(args.provider_uri)
    instruments = parse_instruments(args.instrument, all_inst)
    custom = custom.loc[custom["instrument"].isin(instruments)].copy()
    if custom.empty:
        raise ValueError("custom factor panel is empty after instrument filter")

    start_time = custom["datetime"].min()
    end_time = custom["datetime"].max()
    alpha = prepare_alpha158_panel(
        provider_uri=args.provider_uri,
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
        sample_minutes=args.sample_minutes,
    )
    if alpha.empty:
        raise ValueError("alpha158 panel is empty")

    custom_reserved = {"instrument", "datetime", "future_return", "target"}
    custom_renamed = custom.copy()
    rename_map = {c: f"custom__{c}" for c in custom.columns if c not in custom_reserved}
    custom_renamed = custom_renamed.rename(columns=rename_map)

    merged = custom_renamed.merge(
        alpha,
        on=["instrument", "datetime"],
        how="inner",
        suffixes=("", "_alpha"),
    )
    # Prefer custom label to keep consistency with factor mining panel.
    if "future_return_alpha" in merged.columns:
        merged = merged.drop(columns=["future_return_alpha"])
    if "target_alpha" in merged.columns:
        merged = merged.drop(columns=["target_alpha"])

    vcfg = ValidationConfig(
        factor_panel=str(custom_panel_path),
        output_dir=str(out_dir),
        factor_rankings=None,
        factor_rankings_by_instrument=None,
        top_k=0,
        eval_quantile=args.eval_quantile,
        break_even_winrate=args.break_even_winrate,
        payout_win=args.payout_win,
        payout_loss=args.payout_loss,
        rolling_window_samples=args.rolling_window_samples,
        rolling_step_samples=args.rolling_step_samples,
        min_samples=args.min_samples,
    )

    all_res = evaluate_factor_panel(merged, vcfg)
    if all_res.empty:
        raise ValueError("no factor evaluation results")
    all_res["source"] = all_res["factor"].apply(
        lambda x: "alpha158" if str(x).startswith("alpha158__") else "custom"
    )

    custom_res = all_res.loc[all_res["source"] == "custom"].copy().reset_index(drop=True)
    alpha_res = all_res.loc[all_res["source"] == "alpha158"].copy().reset_index(drop=True)

    by_inst_frames: List[pd.DataFrame] = []
    by_inst_summary_rows: List[Dict] = []
    for inst in instruments:
        sub = merged.loc[merged["instrument"] == inst].copy()
        sub_res = evaluate_factor_panel(sub, vcfg)
        if sub_res.empty:
            continue
        sub_res["source"] = sub_res["factor"].apply(
            lambda x: "alpha158" if str(x).startswith("alpha158__") else "custom"
        )
        sub_res.insert(0, "instrument", inst)
        by_inst_frames.append(sub_res)

        sub_custom = sub_res.loc[sub_res["source"] == "custom"].copy().reset_index(drop=True)
        sub_alpha = sub_res.loc[sub_res["source"] == "alpha158"].copy().reset_index(drop=True)
        row = {"instrument": inst}
        if not sub_custom.empty:
            row.update(
                {
                    "best_custom_factor": sub_custom.iloc[0]["factor"],
                    "best_custom_edge": float(sub_custom.iloc[0]["edge_vs_break_even"]),
                    "best_custom_expected_pnl": float(sub_custom.iloc[0]["expected_pnl_per_trade"]),
                }
            )
        else:
            row.update(
                {
                    "best_custom_factor": None,
                    "best_custom_edge": float("nan"),
                    "best_custom_expected_pnl": float("nan"),
                }
            )
        if not sub_alpha.empty:
            row.update(
                {
                    "best_alpha158_factor": sub_alpha.iloc[0]["factor"],
                    "best_alpha158_edge": float(sub_alpha.iloc[0]["edge_vs_break_even"]),
                    "best_alpha158_expected_pnl": float(sub_alpha.iloc[0]["expected_pnl_per_trade"]),
                }
            )
        else:
            row.update(
                {
                    "best_alpha158_factor": None,
                    "best_alpha158_edge": float("nan"),
                    "best_alpha158_expected_pnl": float("nan"),
                }
            )
        if pd.notna(row["best_custom_edge"]) and pd.notna(row["best_alpha158_edge"]):
            row["best_source_by_edge"] = "custom" if row["best_custom_edge"] >= row["best_alpha158_edge"] else "alpha158"
            row["edge_gap_custom_minus_alpha"] = float(row["best_custom_edge"] - row["best_alpha158_edge"])
        else:
            row["best_source_by_edge"] = None
            row["edge_gap_custom_minus_alpha"] = float("nan")
        by_inst_summary_rows.append(row)

    by_inst_df = pd.concat(by_inst_frames, ignore_index=True) if by_inst_frames else pd.DataFrame()
    by_inst_summary_df = pd.DataFrame(by_inst_summary_rows)

    def _source_summary(df: pd.DataFrame, source: str) -> Dict:
        if df.empty:
            return {"source": source, "n_factors": 0}
        return {
            "source": source,
            "n_factors": int(len(df)),
            "best_edge": float(df["edge_vs_break_even"].max()),
            "mean_edge": float(df["edge_vs_break_even"].mean()),
            "median_edge": float(df["edge_vs_break_even"].median()),
            "best_expected_pnl": float(df["expected_pnl_per_trade"].max()),
            "mean_expected_pnl": float(df["expected_pnl_per_trade"].mean()),
            "mean_auc": float(df["auc_best"].mean()),
            "positive_edge_ratio": float((df["edge_vs_break_even"] > 0).mean()),
            "top_factor": str(df.iloc[0]["factor"]),
        }

    source_cmp = pd.DataFrame([_source_summary(custom_res, "custom"), _source_summary(alpha_res, "alpha158")])

    all_res.to_csv(out_dir / "factor_backtest_comparison_all.csv", index=False)
    custom_res.to_csv(out_dir / "factor_backtest_comparison_custom.csv", index=False)
    alpha_res.to_csv(out_dir / "factor_backtest_comparison_alpha158.csv", index=False)
    source_cmp.to_csv(out_dir / "source_summary.csv", index=False)
    by_inst_df.to_csv(out_dir / "factor_backtest_comparison_all_by_instrument.csv", index=False)
    by_inst_summary_df.to_csv(out_dir / "source_summary_by_instrument.csv", index=False)

    summary = {
        "config": vars(args),
        "n_instruments": len(instruments),
        "instruments": instruments,
        "n_rows_merged": int(len(merged)),
        "n_factors_all": int(len(all_res)),
        "n_factors_custom": int(len(custom_res)),
        "n_factors_alpha158": int(len(alpha_res)),
        "n_factors_by_instrument": int(len(by_inst_df)),
        "source_summary": source_cmp.to_dict(orient="records"),
        "source_summary_by_instrument": by_inst_summary_df.to_dict(orient="records"),
        "top10_all": all_res.head(10).to_dict(orient="records"),
        "top10_custom": custom_res.head(10).to_dict(orient="records"),
        "top10_alpha158": alpha_res.head(10).to_dict(orient="records"),
        "output_dir": str(out_dir),
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare custom factors with Alpha158 on unified time-series backtest metrics")
    parser.add_argument(
        "--custom-factor-panel",
        default="a6_customizations/qlib_btc_5min_factor_mining/outputs/mine_all_unds_30d/factor_panel.parquet",
    )
    parser.add_argument(
        "--provider-uri",
        default="a6_customizations/binance_data-qlib/qlib_data_1min",
    )
    parser.add_argument("--instrument", default="ALL", help="ALL or comma-separated symbols")
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--eval-quantile", type=float, default=0.2)
    parser.add_argument("--break-even-winrate", type=float, default=0.5882)
    parser.add_argument("--payout-win", type=float, default=3.5)
    parser.add_argument("--payout-loss", type=float, default=5.0)
    parser.add_argument("--rolling-window-samples", type=int, default=2016)
    parser.add_argument("--rolling-step-samples", type=int, default=288)
    parser.add_argument("--min-samples", type=int, default=1000)
    parser.add_argument(
        "--output-dir",
        default="a6_customizations/qlib_btc_5min_factor_mining/outputs/compare_custom_vs_alpha158",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(run_compare(args), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
