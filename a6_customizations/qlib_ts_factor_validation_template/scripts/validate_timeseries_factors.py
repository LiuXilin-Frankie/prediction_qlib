#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class ValidationConfig:
    factor_panel: str
    output_dir: str
    factor_rankings: str | None = None
    factor_rankings_by_instrument: str | None = None
    top_k: int = 30
    eval_quantile: float = 0.2
    break_even_winrate: float = 0.5882
    payout_win: float = 3.5
    payout_loss: float = 5.0
    rolling_window_samples: int = 2016
    rolling_step_samples: int = 288
    min_samples: int = 1000


def auc_binary(y_true: np.ndarray, score: np.ndarray) -> float:
    mask = np.isfinite(score) & np.isfinite(y_true)
    y = y_true[mask].astype(int)
    s = score[mask]
    n = len(y)
    if n == 0:
        return float("nan")
    pos = y.sum()
    neg = n - pos
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    rank_sum_pos = ranks[y == 1].sum()
    u = rank_sum_pos - pos * (pos + 1) / 2.0
    return float(u / (pos * neg))


def longest_losing_streak(win_flags: np.ndarray) -> int:
    longest = 0
    current = 0
    for is_win in win_flags:
        if not bool(is_win):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _evaluate_side(y: np.ndarray, s: np.ndarray, q: float) -> Dict[str, float]:
    lo = np.nanquantile(s, q)
    hi = np.nanquantile(s, 1.0 - q)
    long_mask = s >= hi
    short_mask = s <= lo

    long_n = int(long_mask.sum())
    short_n = int(short_mask.sum())
    long_win = float(np.mean(y[long_mask] == 1)) if long_n > 0 else float("nan")
    short_win = float(np.mean(y[short_mask] == 0)) if short_n > 0 else float("nan")

    if np.isnan(long_win) and np.isnan(short_win):
        best_side = "none"
        best_win = float("nan")
        best_n = 0
        best_flags = np.array([], dtype=bool)
    elif np.isnan(short_win) or (not np.isnan(long_win) and long_win >= short_win):
        best_side = "long"
        best_win = long_win
        best_n = long_n
        best_flags = y[long_mask] == 1
    else:
        best_side = "short"
        best_win = short_win
        best_n = short_n
        best_flags = y[short_mask] == 0

    return {
        "long_n": long_n,
        "short_n": short_n,
        "long_winrate": long_win,
        "short_winrate": short_win,
        "best_side": best_side,
        "best_n": best_n,
        "best_winrate": best_win,
        "best_win_flags": best_flags,
    }


def evaluate_factor(
    factor_name: str,
    df: pd.DataFrame,
    cfg: ValidationConfig,
) -> Tuple[Dict, List[Dict]]:
    y_all = df["target"].to_numpy()
    s_all = df[factor_name].to_numpy(dtype=float)
    dt_all = pd.to_datetime(df["datetime"])

    mask = np.isfinite(y_all) & np.isfinite(s_all)
    n = int(mask.sum())
    if n < cfg.min_samples:
        return {}, []

    y = y_all[mask].astype(int)
    s = s_all[mask]
    dt = dt_all[mask]

    auc_pos = auc_binary(y, s)
    auc_neg = auc_binary(y, -s)
    sign = 1 if (np.isnan(auc_neg) or (not np.isnan(auc_pos) and auc_pos >= auc_neg)) else -1
    s_eff = s * sign
    auc_best = auc_pos if sign == 1 else auc_neg

    side_eval = _evaluate_side(y, s_eff, cfg.eval_quantile)
    best_winrate = side_eval["best_winrate"]
    expected_pnl = (
        best_winrate * cfg.payout_win - (1.0 - best_winrate) * cfg.payout_loss
        if not np.isnan(best_winrate)
        else float("nan")
    )
    edge = best_winrate - cfg.break_even_winrate if not np.isnan(best_winrate) else float("nan")
    lose_streak = longest_losing_streak(side_eval["best_win_flags"]) if side_eval["best_n"] > 0 else 0

    factor_summary = {
        "factor": factor_name,
        "samples": n,
        "sign": sign,
        "auc_best": auc_best,
        "best_side": side_eval["best_side"],
        "best_tail_samples": int(side_eval["best_n"]),
        "best_tail_winrate": best_winrate,
        "edge_vs_break_even": edge,
        "expected_pnl_per_trade": expected_pnl,
        "longest_losing_streak": lose_streak,
        "long_tail_samples": int(side_eval["long_n"]),
        "long_tail_winrate": side_eval["long_winrate"],
        "short_tail_samples": int(side_eval["short_n"]),
        "short_tail_winrate": side_eval["short_winrate"],
    }

    rolling_rows: List[Dict] = []
    w = int(cfg.rolling_window_samples)
    step = int(cfg.rolling_step_samples)
    for end in range(w, n + 1, step):
        left = end - w
        y_w = y[left:end]
        s_w = s_eff[left:end]
        dt_end = dt.iloc[end - 1]
        auc_w = auc_binary(y_w, s_w)
        side_w = _evaluate_side(y_w, s_w, cfg.eval_quantile)
        best_win_w = side_w["best_winrate"]
        edge_w = best_win_w - cfg.break_even_winrate if not np.isnan(best_win_w) else float("nan")
        rolling_rows.append(
            {
                "factor": factor_name,
                "window_end": dt_end,
                "window_samples": w,
                "rolling_auc": auc_w,
                "rolling_best_tail_winrate": best_win_w,
                "rolling_edge_vs_break_even": edge_w,
                "rolling_best_side": side_w["best_side"],
                "rolling_best_tail_samples": int(side_w["best_n"]),
            }
        )

    if rolling_rows:
        rolling_df = pd.DataFrame(rolling_rows)
        factor_summary["rolling_edge_mean"] = float(rolling_df["rolling_edge_vs_break_even"].mean())
        factor_summary["rolling_edge_p10"] = float(rolling_df["rolling_edge_vs_break_even"].quantile(0.1))
        factor_summary["rolling_edge_positive_ratio"] = float(
            (rolling_df["rolling_edge_vs_break_even"] > 0.0).mean()
        )
    else:
        factor_summary["rolling_edge_mean"] = float("nan")
        factor_summary["rolling_edge_p10"] = float("nan")
        factor_summary["rolling_edge_positive_ratio"] = float("nan")

    return factor_summary, rolling_rows


def get_candidate_factors(df: pd.DataFrame, ranking_path: str | None, top_k: int) -> List[str]:
    reserved = {"datetime", "future_return", "target"}
    all_factors = [c for c in df.columns if c not in reserved]
    if not ranking_path:
        return all_factors

    ranking_df = pd.read_csv(ranking_path)
    ranked = [c for c in ranking_df["factor"].tolist() if c in all_factors]
    if top_k <= 0:
        return ranked
    return ranked[:top_k]


def get_candidate_factors_for_instrument(
    df: pd.DataFrame,
    ranking_path: str | None,
    instrument: str,
    top_k: int,
) -> List[str]:
    reserved = {"instrument", "datetime", "future_return", "target"}
    all_factors = [c for c in df.columns if c not in reserved]
    if not ranking_path:
        return all_factors

    ranking_df = pd.read_csv(ranking_path)
    if "instrument" not in ranking_df.columns:
        return get_candidate_factors(df, ranking_path, top_k)
    sub = ranking_df.loc[ranking_df["instrument"] == instrument]
    ranked = [c for c in sub["factor"].tolist() if c in all_factors]
    if top_k <= 0:
        return ranked
    return ranked[:top_k]


def _evaluate_candidates(df: pd.DataFrame, candidates: List[str], cfg: ValidationConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    summaries: List[Dict] = []
    rolling_all: List[Dict] = []
    for factor in candidates:
        summary, rolling_rows = evaluate_factor(factor, df, cfg)
        if summary:
            summaries.append(summary)
            rolling_all.extend(rolling_rows)
    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(
            by=["edge_vs_break_even", "rolling_edge_p10", "auc_best", "samples"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)
    rolling_df = pd.DataFrame(rolling_all)
    return summary_df, rolling_df


def run_validation(cfg: ValidationConfig) -> Dict:
    factor_panel_path = Path(cfg.factor_panel).resolve()
    out_dir = Path(cfg.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(factor_panel_path)
    if "datetime" not in df.columns or "target" not in df.columns:
        raise ValueError("factor_panel must include columns: datetime, target")
    if "instrument" not in df.columns:
        df["instrument"] = "UNKNOWN"

    all_candidates = get_candidate_factors(df, cfg.factor_rankings, cfg.top_k)
    summary_all_df, rolling_all_df = _evaluate_candidates(df, all_candidates, cfg)
    if not summary_all_df.empty:
        summary_all_df.insert(0, "scope", "ALL")
        summary_all_df.insert(1, "instrument", "ALL")
    if not rolling_all_df.empty:
        rolling_all_df.insert(0, "scope", "ALL")
        rolling_all_df.insert(1, "instrument", "ALL")

    summary_inst_frames: List[pd.DataFrame] = []
    rolling_inst_frames: List[pd.DataFrame] = []
    instruments = sorted(df["instrument"].astype(str).unique().tolist())
    for inst in instruments:
        sub = df.loc[df["instrument"] == inst].copy()
        inst_candidates = get_candidate_factors_for_instrument(
            df=sub,
            ranking_path=cfg.factor_rankings_by_instrument or cfg.factor_rankings,
            instrument=inst,
            top_k=cfg.top_k,
        )
        summary_i, rolling_i = _evaluate_candidates(sub, inst_candidates, cfg)
        if not summary_i.empty:
            summary_i.insert(0, "scope", "BY_INSTRUMENT")
            summary_i.insert(1, "instrument", inst)
            summary_inst_frames.append(summary_i)
        if not rolling_i.empty:
            rolling_i.insert(0, "scope", "BY_INSTRUMENT")
            rolling_i.insert(1, "instrument", inst)
            rolling_inst_frames.append(rolling_i)

    summary_inst_df = pd.concat(summary_inst_frames, ignore_index=True) if summary_inst_frames else pd.DataFrame()
    rolling_inst_df = pd.concat(rolling_inst_frames, ignore_index=True) if rolling_inst_frames else pd.DataFrame()

    # Legacy names keep compatibility (ALL scope)
    summary_all_df.to_csv(out_dir / "ts_factor_validation_summary.csv", index=False)
    rolling_all_df.to_csv(out_dir / "ts_factor_validation_rolling.csv", index=False)
    summary_all_df.to_csv(out_dir / "ts_factor_validation_summary_all.csv", index=False)
    rolling_all_df.to_csv(out_dir / "ts_factor_validation_rolling_all.csv", index=False)
    summary_inst_df.to_csv(out_dir / "ts_factor_validation_summary_by_instrument.csv", index=False)
    rolling_inst_df.to_csv(out_dir / "ts_factor_validation_rolling_by_instrument.csv", index=False)

    payload = {
        "config": asdict(cfg),
        "n_instruments": len(instruments),
        "instruments": instruments,
        "n_factor_candidates_all": len(all_candidates),
        "n_factor_evaluated_all": int(len(summary_all_df)),
        "n_rolling_rows_all": int(len(rolling_all_df)),
        "n_factor_evaluated_by_instrument": int(len(summary_inst_df)),
        "n_rolling_rows_by_instrument": int(len(rolling_inst_df)),
        "top10_all": summary_all_df.head(10).to_dict(orient="records"),
        "top10_by_instrument": summary_inst_df.groupby("instrument", as_index=False).head(3).to_dict(orient="records")
        if not summary_inst_df.empty
        else [],
        "output_dir": str(out_dir),
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Time-series factor validation template for event contracts")
    parser.add_argument("--factor-panel", required=True, help="Parquet path generated by factor mining")
    parser.add_argument("--factor-rankings", default=None, help="Optional factor ranking csv")
    parser.add_argument(
        "--factor-rankings-by-instrument",
        default=None,
        help="Optional factor ranking csv with instrument column",
    )
    parser.add_argument("--top-k", type=int, default=30, help="Top-k ranked factors to evaluate; <=0 means all")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--eval-quantile", type=float, default=0.2)
    parser.add_argument("--break-even-winrate", type=float, default=0.5882)
    parser.add_argument("--payout-win", type=float, default=3.5)
    parser.add_argument("--payout-loss", type=float, default=5.0)
    parser.add_argument("--rolling-window-samples", type=int, default=2016)
    parser.add_argument("--rolling-step-samples", type=int, default=288)
    parser.add_argument("--min-samples", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = ValidationConfig(
        factor_panel=args.factor_panel,
        factor_rankings=args.factor_rankings,
        factor_rankings_by_instrument=args.factor_rankings_by_instrument,
        top_k=args.top_k,
        output_dir=args.output_dir,
        eval_quantile=args.eval_quantile,
        break_even_winrate=args.break_even_winrate,
        payout_win=args.payout_win,
        payout_loss=args.payout_loss,
        rolling_window_samples=args.rolling_window_samples,
        rolling_step_samples=args.rolling_step_samples,
        min_samples=args.min_samples,
    )
    print(json.dumps(run_validation(cfg), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
