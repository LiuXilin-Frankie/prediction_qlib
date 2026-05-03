#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import qlib
import yaml
from qlib.data import D


_QLIB_INITIALIZED = False


@dataclass
class MiningConfig:
    plan_path: str
    provider_uri: str = "a6_customizations/binance_data-qlib/qlib_data_1min"
    instrument: str = "BTCUSDT"
    freq: str = "1min"
    entry_offset_minutes: int = 1
    horizon_minutes: int = 5
    sample_minutes: int = 5
    lookback_days: Optional[int] = 180
    output_dir: str = "a6_customizations/qlib_btc_5min_factor_mining/outputs/latest"
    eval_quantile: float = 0.2
    min_samples_per_factor: int = 500
    eps: float = 1e-12


def init_qlib(provider_uri: str) -> None:
    global _QLIB_INITIALIZED
    if _QLIB_INITIALIZED:
        return
    qlib.init(
        provider_uri=str(Path(provider_uri).resolve()),
        expression_cache=None,
        dataset_cache=None,
    )
    _QLIB_INITIALIZED = True


def load_plan(plan_path: str) -> Dict[str, Any]:
    with Path(plan_path).resolve().open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_instrument_range(provider_uri: str, instrument: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    inst_path = Path(provider_uri).resolve() / "instruments" / "all.txt"
    inst_df = pd.read_csv(inst_path, sep="\t", header=None, names=["instrument", "start_time", "end_time"])
    row = inst_df.loc[inst_df["instrument"] == instrument]
    if row.empty:
        raise ValueError(f"Instrument {instrument} not found in {inst_path}")
    return pd.Timestamp(row.iloc[0]["start_time"]), pd.Timestamp(row.iloc[0]["end_time"])


def get_all_instruments(provider_uri: str) -> List[str]:
    inst_path = Path(provider_uri).resolve() / "instruments" / "all.txt"
    inst_df = pd.read_csv(inst_path, sep="\t", header=None, names=["instrument", "start_time", "end_time"])
    return sorted(inst_df["instrument"].astype(str).tolist())


def parse_instrument_list(provider_uri: str, instrument_arg: str) -> List[str]:
    raw = str(instrument_arg).strip()
    if raw.lower() == "all":
        return get_all_instruments(provider_uri)
    items = [s.strip() for s in raw.split(",") if s.strip()]
    if not items:
        raise ValueError("instrument argument is empty. use one symbol, comma list, or ALL")
    return items


def _safe_div(a: pd.Series, b: pd.Series, eps: float) -> pd.Series:
    return a / (b.abs() + eps)


def _zscore(s: pd.Series, window: int, eps: float) -> pd.Series:
    m = s.rolling(window, min_periods=window).mean()
    std = s.rolling(window, min_periods=window).std()
    return (s - m) / (std + eps)


def fetch_base_frame(cfg: MiningConfig, instrument: Optional[str] = None) -> pd.DataFrame:
    instrument = instrument or cfg.instrument
    data_start, data_end = get_instrument_range(cfg.provider_uri, instrument)
    end_time = data_end
    if cfg.lookback_days is not None and cfg.lookback_days > 0:
        start_candidate = data_end - pd.Timedelta(days=int(cfg.lookback_days))
        start_time = max(data_start, start_candidate)
    else:
        start_time = data_start

    fields = [
        "$open",
        "$high",
        "$low",
        "$close",
        "$volume",
        "$quote_volume",
        "$taker_buy_volume",
        "$taker_buy_quote_volume",
    ]
    names = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_volume",
        "taker_buy_quote_volume",
    ]
    df = D.features(
        instruments=[instrument],
        fields=fields,
        start_time=start_time,
        end_time=end_time,
        freq=cfg.freq,
    )
    df.columns = names
    df = df.reset_index()
    if "datetime" not in df.columns:
        raise ValueError("Fetched data does not contain datetime index/column.")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    sample_mask = (df["datetime"].dt.minute % cfg.sample_minutes == 0) & (df["datetime"].dt.second == 0)
    df = df.loc[sample_mask].copy()
    if df.empty:
        raise ValueError("Sampled frame is empty. Please check sample_minutes or data range.")

    # NOTE:
    # After sampling (e.g. sample_minutes=5), shift is applied on sampled rows.
    # So entry_offset_minutes / horizon_minutes act like "sampled step offsets".
    exit_offset = cfg.entry_offset_minutes + cfg.horizon_minutes
    entry_open = df["open"].shift(-cfg.entry_offset_minutes)
    exit_open = df["open"].shift(-exit_offset)
    df["future_return"] = exit_open / entry_open - 1.0
    df["target"] = (df["future_return"] > 0.0).astype(int)
    df["instrument"] = instrument
    df = df.dropna(subset=["future_return"]).reset_index(drop=True)
    return df


def compute_factors(df: pd.DataFrame, plan: Dict[str, Any], eps: float) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    volume = df["volume"]
    quote_volume = df["quote_volume"]
    taker_buy_base = df["taker_buy_volume"]

    factor_cfg = {f["name"]: f for f in plan.get("factors", []) if f.get("enabled", True)}
    construction_mode = (
        str(plan.get("meta", {}).get("feature_construction", "ohlcv_default")).strip().lower()
    )

    if "ema_gap" in factor_cfg:
        p = factor_cfg["ema_gap"]["params"]
        for fast in p.get("fast", []):
            ema_f = close.ewm(span=int(fast), adjust=False, min_periods=int(fast)).mean()
            for slow in p.get("slow", []):
                if fast >= slow:
                    continue
                ema_s = close.ewm(span=int(slow), adjust=False, min_periods=int(slow)).mean()
                col = f"ema_gap_f{fast}_s{slow}"
                out[col] = _safe_div(ema_f - ema_s, close, eps)

    if "macd_hist" in factor_cfg:
        p = factor_cfg["macd_hist"]["params"]
        for fast in p.get("fast", []):
            ema_f = close.ewm(span=int(fast), adjust=False, min_periods=int(fast)).mean()
            for slow in p.get("slow", []):
                if fast >= slow:
                    continue
                ema_s = close.ewm(span=int(slow), adjust=False, min_periods=int(slow)).mean()
                macd = ema_f - ema_s
                for signal in p.get("signal", []):
                    sig = macd.ewm(span=int(signal), adjust=False, min_periods=int(signal)).mean()
                    out[f"macd_hist_f{fast}_s{slow}_sig{signal}"] = _safe_div(macd - sig, close, eps)

    if "rsi" in factor_cfg:
        p = factor_cfg["rsi"]["params"]
        delta = close.diff()
        up = delta.clip(lower=0.0)
        down = (-delta).clip(lower=0.0)
        for w in p.get("window", []):
            w = int(w)
            up_avg = up.ewm(alpha=1.0 / w, adjust=False, min_periods=w).mean()
            down_avg = down.ewm(alpha=1.0 / w, adjust=False, min_periods=w).mean()
            rs = up_avg / (down_avg + eps)
            out[f"rsi_{w}"] = 100.0 - 100.0 / (1.0 + rs)

    if "roc" in factor_cfg:
        p = factor_cfg["roc"]["params"]
        for w in p.get("window", []):
            w = int(w)
            out[f"roc_{w}"] = close.pct_change(w)

    prev_close = close.shift(1)
    if construction_mode == "close_5min_only":
        # close-only proxy for true range under t, t-5, t-10... construction
        tr = (close - prev_close).abs()
    else:
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

    if "atr_norm" in factor_cfg:
        p = factor_cfg["atr_norm"]["params"]
        for w in p.get("window", []):
            w = int(w)
            atr = tr.rolling(w, min_periods=w).mean()
            out[f"atr_norm_{w}"] = _safe_div(atr, close, eps)

    if "realized_vol" in factor_cfg:
        p = factor_cfg["realized_vol"]["params"]
        log_ret = np.log(close / close.shift(1))
        for w in p.get("window", []):
            w = int(w)
            out[f"realized_vol_{w}"] = log_ret.rolling(w, min_periods=w).std()

    if "bollinger_bandwidth" in factor_cfg:
        p = factor_cfg["bollinger_bandwidth"]["params"]
        n_std = float(p.get("n_std", [2.0])[0])
        for w in p.get("window", []):
            w = int(w)
            ma = close.rolling(w, min_periods=w).mean()
            std = close.rolling(w, min_periods=w).std()
            out[f"bb_width_{w}_n{n_std:g}"] = _safe_div(2.0 * n_std * std, ma, eps)

    if "obv_zscore" in factor_cfg:
        p = factor_cfg["obv_zscore"]["params"]
        sign = np.sign(close.diff()).fillna(0.0)
        if construction_mode == "close_5min_only":
            obv = sign.cumsum()
        else:
            obv = (sign * volume.fillna(0.0)).cumsum()
        for sw in p.get("smooth_window", []):
            sw = int(sw)
            obv_s = obv.ewm(span=sw, adjust=False, min_periods=sw).mean()
            for zw in p.get("zscore_window", []):
                zw = int(zw)
                out[f"obv_z_sw{sw}_zw{zw}"] = _zscore(obv_s, zw, eps)

    if "mfi" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["mfi"]["params"]
        typical = (high + low + close) / 3.0
        money_flow = typical * volume
        tp_diff = typical.diff()
        pos_mf = money_flow.where(tp_diff > 0.0, 0.0)
        neg_mf = money_flow.where(tp_diff < 0.0, 0.0).abs()
        for w in p.get("window", []):
            w = int(w)
            pos = pos_mf.rolling(w, min_periods=w).sum()
            neg = neg_mf.rolling(w, min_periods=w).sum()
            mfr = pos / (neg + eps)
            out[f"mfi_{w}"] = 100.0 - 100.0 / (1.0 + mfr)

    if "cmf" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["cmf"]["params"]
        mfm = ((close - low) - (high - close)) / ((high - low) + eps)
        mfv = mfm * volume
        for w in p.get("window", []):
            w = int(w)
            out[f"cmf_{w}"] = mfv.rolling(w, min_periods=w).sum() / (volume.rolling(w, min_periods=w).sum() + eps)

    if "taker_buy_ratio" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["taker_buy_ratio"]["params"]
        ratio = _safe_div(taker_buy_base, volume, eps)
        out["taker_buy_ratio_raw"] = ratio
        for w in p.get("smooth_window", []):
            w = int(w)
            out[f"taker_buy_ratio_{w}"] = ratio.rolling(w, min_periods=w).mean()

    if "candle_microstructure" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["candle_microstructure"]["params"]
        rng = (high - low).abs()
        body = (close - open_).abs()
        upper_shadow = high - np.maximum(open_, close)
        lower_shadow = np.minimum(open_, close) - low
        clv = ((close - low) - (high - close)) / (rng + eps)
        base = {
            "high_low_range_norm": _safe_div(rng, close, eps),
            "body_to_range": body / (rng + eps),
            "upper_shadow_ratio": upper_shadow / (rng + eps),
            "lower_shadow_ratio": lower_shadow / (rng + eps),
            "close_location_value": clv,
            "quote_vol_ratio": _safe_div(quote_volume, volume * close, eps),
        }
        for name in p.get("include", []):
            if name in base:
                out[name] = base[name]
        for w in p.get("smooth_window", []):
            w = int(w)
            for name in p.get("include", []):
                if name in base:
                    out[f"{name}_ma{w}"] = base[name].rolling(w, min_periods=w).mean()

    return out


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


def evaluate_factors(
    merged_df: pd.DataFrame,
    break_even_winrate: float,
    eval_quantile: float,
    min_samples_per_factor: int,
) -> pd.DataFrame:
    y = merged_df["target"].to_numpy()
    rows: List[Dict[str, Any]] = []
    factor_cols = [c for c in merged_df.columns if c not in {"instrument", "datetime", "future_return", "target"}]
    q = float(eval_quantile)

    for col in factor_cols:
        s = merged_df[col].to_numpy(dtype=float)
        mask = np.isfinite(s) & np.isfinite(y)
        n = int(mask.sum())
        if n < min_samples_per_factor:
            continue
        y_m = y[mask]
        s_m = s[mask]
        auc_raw = auc_binary(y_m, s_m)
        auc_inv = auc_binary(y_m, -s_m)
        use_sign = 1.0 if (np.isnan(auc_inv) or (not np.isnan(auc_raw) and auc_raw >= auc_inv)) else -1.0
        auc_best = auc_raw if use_sign > 0 else auc_inv
        s_eff = s_m * use_sign

        lo = np.nanquantile(s_eff, q)
        hi = np.nanquantile(s_eff, 1.0 - q)
        long_mask = s_eff >= hi
        short_mask = s_eff <= lo
        long_n = int(long_mask.sum())
        short_n = int(short_mask.sum())
        long_win = float(np.mean(y_m[long_mask] == 1)) if long_n > 0 else float("nan")
        short_win = float(np.mean(y_m[short_mask] == 0)) if short_n > 0 else float("nan")
        best_tail_win = np.nanmax([long_win, short_win])
        edge = best_tail_win - break_even_winrate if not np.isnan(best_tail_win) else float("nan")

        rows.append(
            {
                "factor": col,
                "samples": n,
                "sign": int(use_sign),
                "auc_best": auc_best,
                "long_tail_n": long_n,
                "long_tail_winrate": long_win,
                "short_tail_n": short_n,
                "short_tail_winrate": short_win,
                "best_tail_winrate": best_tail_win,
                "edge_vs_break_even": edge,
            }
        )

    res = pd.DataFrame(rows)
    if res.empty:
        return res
    return res.sort_values(
        by=["edge_vs_break_even", "auc_best", "samples"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def run_mining(cfg: MiningConfig) -> Dict[str, Any]:
    plan = load_plan(cfg.plan_path)
    status = str(plan.get("meta", {}).get("status", "proposed")).strip().lower()
    if status != "confirmed":
        raise ValueError("plan status must be confirmed before mining.")

    init_qlib(cfg.provider_uri)
    instruments = parse_instrument_list(cfg.provider_uri, cfg.instrument)
    merged_frames: List[pd.DataFrame] = []
    for instrument in instruments:
        base_df = fetch_base_frame(cfg, instrument=instrument)
        factor_df = compute_factors(base_df, plan, cfg.eps)
        merged_i = pd.concat(
            [
                base_df[["instrument", "datetime", "future_return", "target"]].reset_index(drop=True),
                factor_df.reset_index(drop=True),
            ],
            axis=1,
        )
        merged_frames.append(merged_i)
    merged = pd.concat(merged_frames, ignore_index=True)
    break_even = float(plan.get("meta", {}).get("objective", {}).get("break_even_winrate", 0.5882))
    rank_df = evaluate_factors(merged, break_even, cfg.eval_quantile, cfg.min_samples_per_factor)
    rank_by_inst = []
    for instrument in instruments:
        sub = merged.loc[merged["instrument"] == instrument].copy()
        sub_rank = evaluate_factors(sub, break_even, cfg.eval_quantile, cfg.min_samples_per_factor)
        if sub_rank.empty:
            continue
        sub_rank.insert(0, "instrument", instrument)
        rank_by_inst.append(sub_rank)
    rank_by_inst_df = pd.concat(rank_by_inst, ignore_index=True) if rank_by_inst else pd.DataFrame()

    out_dir = Path(cfg.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out_dir / "factor_panel.parquet", index=False)
    rank_df.to_csv(out_dir / "factor_rankings.csv", index=False)
    rank_by_inst_df.to_csv(out_dir / "factor_rankings_by_instrument.csv", index=False)

    summary = {
        "config": asdict(cfg),
        "plan_name": plan.get("meta", {}).get("plan_name"),
        "status": status,
        "n_instruments": len(instruments),
        "instruments": instruments,
        "n_rows": int(len(merged)),
        "n_factor_columns": int(max(0, merged.shape[1] - 4)),
        "n_ranked_factors": int(len(rank_df)),
        "n_ranked_factors_by_instrument": int(len(rank_by_inst_df)),
        "top10": rank_df.head(10).to_dict(orient="records"),
        "output_dir": str(out_dir),
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    return summary
