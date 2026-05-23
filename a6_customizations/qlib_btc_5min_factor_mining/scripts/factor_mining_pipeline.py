#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import qlib
import yaml
from qlib.data import D


_QLIB_INITIALIZED = False

RESERVED_COLUMNS = {"instrument", "datetime", "future_return", "target"}


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


def _safe_div(a: pd.Series | np.ndarray | float, b: pd.Series | np.ndarray | float, eps: float) -> pd.Series:
    a_s = pd.Series(a) if not isinstance(a, pd.Series) else a
    b_s = pd.Series(b, index=a_s.index) if not isinstance(b, pd.Series) else b
    return a_s / (b_s.abs() + eps)


def _zscore(s: pd.Series, window: int, eps: float) -> pd.Series:
    m = s.rolling(window, min_periods=window).mean()
    std = s.rolling(window, min_periods=window).std()
    return (s - m) / (std + eps)


def _rolling_rank_pct(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).apply(lambda arr: float(np.mean(arr <= arr[-1])), raw=True)


def _weighted_rolling_sum(s: pd.Series, weights: np.ndarray) -> pd.Series:
    return s.rolling(len(weights), min_periods=len(weights)).apply(lambda arr: float(np.dot(arr, weights)), raw=True)


def _decay_linear(s: pd.Series, window: int) -> pd.Series:
    weights = np.arange(1, window + 1, dtype=float)
    weights /= weights.sum()
    return _weighted_rolling_sum(s, weights)


def _regression_stats(s: pd.Series, window: int, eps: float) -> Tuple[pd.Series, pd.Series, pd.Series]:
    x = np.arange(window, dtype=float)
    x_mean = float(x.mean())
    sxx = float(np.square(x - x_mean).sum())
    sum_y = s.rolling(window, min_periods=window).sum()
    sum_y2 = s.pow(2).rolling(window, min_periods=window).sum()
    sum_xy = _weighted_rolling_sum(s, x)
    slope = (sum_xy - x_mean * sum_y) / (sxx + eps)
    y_mean = sum_y / float(window)
    intercept = y_mean - slope * x_mean
    fitted_last = intercept + slope * float(window - 1)
    resid = s - fitted_last
    syy = sum_y2 - float(window) * y_mean.pow(2)
    ss_reg = slope.pow(2) * sxx
    rsqr = ss_reg / (syy + eps)
    rsqr = rsqr.clip(lower=0.0, upper=1.0)
    return slope, rsqr, resid


def _idx_extreme(s: pd.Series, window: int, mode: str) -> pd.Series:
    if mode == "max":
        func = lambda arr: float(len(arr) - 1 - int(np.argmax(arr)))
    elif mode == "min":
        func = lambda arr: float(len(arr) - 1 - int(np.argmin(arr)))
    else:
        raise ValueError(f"unsupported extreme mode: {mode}")
    return s.rolling(window, min_periods=window).apply(func, raw=True)


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
        "$vwap",
        "$volume",
        "$count",
        "$quote_volume",
        "$taker_buy_volume",
        "$taker_buy_quote_volume",
    ]
    names = [
        "open",
        "high",
        "low",
        "close",
        "vwap",
        "volume",
        "count",
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

    exit_offset = cfg.entry_offset_minutes + cfg.horizon_minutes
    entry_open = df["open"].shift(-cfg.entry_offset_minutes)
    exit_open = df["open"].shift(-exit_offset)
    df["future_return"] = exit_open / entry_open - 1.0
    df["target"] = (df["future_return"] > 0.0).astype(int)
    df["instrument"] = instrument
    df = df.dropna(subset=["future_return"]).reset_index(drop=True)
    return df


def compute_factors(df: pd.DataFrame, plan: Dict[str, Any], eps: float) -> Tuple[pd.DataFrame, pd.DataFrame]:
    factor_values: Dict[str, pd.Series] = {}
    metadata_rows: List[Dict[str, Any]] = []

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    vwap = df["vwap"].fillna(close)
    volume = df["volume"].fillna(0.0)
    count = df["count"].fillna(0.0)
    quote_volume = df["quote_volume"].fillna(0.0)
    taker_buy_base = df["taker_buy_volume"].fillna(0.0)
    taker_buy_quote = df["taker_buy_quote_volume"].fillna(0.0)
    ret1 = close.pct_change(1)
    log_ret = np.log(close / close.shift(1))

    factor_cfg = {f["name"]: f for f in plan.get("factors", []) if f.get("enabled", True)}
    construction_mode = str(plan.get("meta", {}).get("feature_construction", "ohlcv_default")).strip().lower()

    def add_factor(plan_name: str, column: str, series: pd.Series) -> None:
        factor_values[column] = series
        cfg = factor_cfg.get(plan_name, {})
        metadata_rows.append(
            {
                "factor": column,
                "plan_factor": plan_name,
                "family": cfg.get("family", "unclassified"),
                "source": cfg.get("source", cfg.get("family", "custom")),
                "status": cfg.get("status", "proposed"),
                "rationale": cfg.get("rationale", ""),
            }
        )

    if "ema_gap" in factor_cfg:
        p = factor_cfg["ema_gap"]["params"]
        for fast in p.get("fast", []):
            ema_f = close.ewm(span=int(fast), adjust=False, min_periods=int(fast)).mean()
            for slow in p.get("slow", []):
                if fast >= slow:
                    continue
                ema_s = close.ewm(span=int(slow), adjust=False, min_periods=int(slow)).mean()
                add_factor("ema_gap", f"ema_gap_f{fast}_s{slow}", _safe_div(ema_f - ema_s, close, eps))

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
                    add_factor(
                        "macd_hist",
                        f"macd_hist_f{fast}_s{slow}_sig{signal}",
                        _safe_div(macd - sig, close, eps),
                    )

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
            add_factor("rsi", f"rsi_{w}", 100.0 - 100.0 / (1.0 + rs))

    if "roc" in factor_cfg:
        p = factor_cfg["roc"]["params"]
        for w in p.get("window", []):
            w = int(w)
            add_factor("roc", f"roc_{w}", close.pct_change(w))

    prev_close = close.shift(1)
    if construction_mode == "close_5min_only":
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
            add_factor("atr_norm", f"atr_norm_{w}", _safe_div(atr, close, eps))

    if "realized_vol" in factor_cfg:
        p = factor_cfg["realized_vol"]["params"]
        for w in p.get("window", []):
            w = int(w)
            add_factor("realized_vol", f"realized_vol_{w}", log_ret.rolling(w, min_periods=w).std())

    if "bollinger_bandwidth" in factor_cfg:
        p = factor_cfg["bollinger_bandwidth"]["params"]
        n_std = float(p.get("n_std", [2.0])[0])
        for w in p.get("window", []):
            w = int(w)
            ma = close.rolling(w, min_periods=w).mean()
            std = close.rolling(w, min_periods=w).std()
            add_factor("bollinger_bandwidth", f"bb_width_{w}_n{n_std:g}", _safe_div(2.0 * n_std * std, ma, eps))

    if "obv_zscore" in factor_cfg:
        p = factor_cfg["obv_zscore"]["params"]
        sign = np.sign(close.diff()).fillna(0.0)
        if construction_mode == "close_5min_only":
            obv = sign.cumsum()
        else:
            obv = (sign * volume).cumsum()
        for sw in p.get("smooth_window", []):
            sw = int(sw)
            obv_s = obv.ewm(span=sw, adjust=False, min_periods=sw).mean()
            for zw in p.get("zscore_window", []):
                zw = int(zw)
                add_factor("obv_zscore", f"obv_z_sw{sw}_zw{zw}", _zscore(obv_s, zw, eps))

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
            add_factor("mfi", f"mfi_{w}", 100.0 - 100.0 / (1.0 + mfr))

    if "cmf" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["cmf"]["params"]
        mfm = ((close - low) - (high - close)) / ((high - low) + eps)
        mfv = mfm * volume
        for w in p.get("window", []):
            w = int(w)
            val = mfv.rolling(w, min_periods=w).sum() / (volume.rolling(w, min_periods=w).sum() + eps)
            add_factor("cmf", f"cmf_{w}", val)

    if "taker_buy_ratio" in factor_cfg and construction_mode != "close_5min_only":
        p = factor_cfg["taker_buy_ratio"]["params"]
        ratio = _safe_div(taker_buy_base, volume, eps)
        add_factor("taker_buy_ratio", "taker_buy_ratio_raw", ratio)
        for w in p.get("smooth_window", []):
            w = int(w)
            add_factor("taker_buy_ratio", f"taker_buy_ratio_{w}", ratio.rolling(w, min_periods=w).mean())

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
                add_factor("candle_microstructure", name, base[name])
        for w in p.get("smooth_window", []):
            w = int(w)
            for name in p.get("include", []):
                if name in base:
                    add_factor("candle_microstructure", f"{name}_ma{w}", base[name].rolling(w, min_periods=w).mean())

    alpha158_windows = None
    if "alpha158_ma" in factor_cfg:
        alpha158_windows = [int(w) for w in factor_cfg["alpha158_ma"]["params"].get("window", [])]
    elif "alpha158_beta" in factor_cfg:
        alpha158_windows = [int(w) for w in factor_cfg["alpha158_beta"]["params"].get("window", [])]

    if alpha158_windows:
        up_flags = (close > close.shift(1)).astype(float)
        down_flags = (close < close.shift(1)).astype(float)
        close_abs_diff = (close - close.shift(1)).abs()
        volume_abs_diff = (volume - volume.shift(1)).abs()
        volume_ret = np.log(_safe_div(volume, volume.shift(1).replace(0.0, np.nan), eps) + 1.0)
        vol_price_shock = close.pct_change(1).abs() * volume
        high_low_range = high - low

        for w in alpha158_windows:
            slope, rsqr, resid = _regression_stats(close, w, eps)
            max_high = high.rolling(w, min_periods=w).max()
            min_low = low.rolling(w, min_periods=w).min()
            close_mean = close.rolling(w, min_periods=w).mean()
            vol_mean = volume.rolling(w, min_periods=w).mean()
            close_sum_diff = close.diff().clip(lower=0.0).rolling(w, min_periods=w).sum()
            close_sum_down = (-close.diff().clip(upper=0.0)).rolling(w, min_periods=w).sum()
            volume_sum_up = volume.diff().clip(lower=0.0).rolling(w, min_periods=w).sum()
            volume_sum_down = (-volume.diff().clip(upper=0.0)).rolling(w, min_periods=w).sum()

            if "alpha158_ma" in factor_cfg:
                add_factor("alpha158_ma", f"alpha158_ma_ratio_{w}", _safe_div(close_mean, close, eps))
            if "alpha158_beta" in factor_cfg:
                add_factor("alpha158_beta", f"alpha158_beta_{w}", _safe_div(slope, close, eps))
            if "alpha158_rsqr" in factor_cfg:
                add_factor("alpha158_rsqr", f"alpha158_rsqr_{w}", rsqr)
            if "alpha158_resi" in factor_cfg:
                add_factor("alpha158_resi", f"alpha158_resi_{w}", _safe_div(resid, close, eps))
            if "alpha158_max" in factor_cfg:
                add_factor("alpha158_max", f"alpha158_max_{w}", _safe_div(max_high, close, eps))
            if "alpha158_min" in factor_cfg:
                add_factor("alpha158_min", f"alpha158_min_{w}", _safe_div(min_low, close, eps))
            if "alpha158_qtlu" in factor_cfg:
                add_factor(
                    "alpha158_qtlu",
                    f"alpha158_qtlu_{w}_q80",
                    _safe_div(close.rolling(w, min_periods=w).quantile(0.8), close, eps),
                )
            if "alpha158_qtld" in factor_cfg:
                add_factor(
                    "alpha158_qtld",
                    f"alpha158_qtld_{w}_q20",
                    _safe_div(close.rolling(w, min_periods=w).quantile(0.2), close, eps),
                )
            if "alpha158_rsv" in factor_cfg:
                add_factor("alpha158_rsv", f"alpha158_rsv_{w}", (close - min_low) / (max_high - min_low + eps))
            if "alpha158_imax" in factor_cfg:
                imax = _idx_extreme(high, w, "max") / float(w)
                add_factor("alpha158_imax", f"alpha158_imax_{w}", imax)
            else:
                imax = None
            if "alpha158_imin" in factor_cfg:
                imin = _idx_extreme(low, w, "min") / float(w)
                add_factor("alpha158_imin", f"alpha158_imin_{w}", imin)
            else:
                imin = None
            if "alpha158_imxd" in factor_cfg:
                if imax is None:
                    imax = _idx_extreme(high, w, "max") / float(w)
                if imin is None:
                    imin = _idx_extreme(low, w, "min") / float(w)
                add_factor("alpha158_imxd", f"alpha158_imxd_{w}", imax - imin)
            if "alpha158_corr" in factor_cfg:
                corr_close_volume = close.rolling(w, min_periods=w).corr(np.log1p(volume))
                add_factor("alpha158_corr", f"alpha158_corr_close_log_volume_{w}", corr_close_volume)
            if "alpha158_cord" in factor_cfg:
                cord = ret1.rolling(w, min_periods=w).corr(volume_ret)
                add_factor("alpha158_cord", f"alpha158_cord_{w}", cord)
            if "alpha158_cntp" in factor_cfg:
                add_factor("alpha158_cntp", f"alpha158_cntp_{w}", up_flags.rolling(w, min_periods=w).mean())
            if "alpha158_cntn" in factor_cfg:
                add_factor("alpha158_cntn", f"alpha158_cntn_{w}", down_flags.rolling(w, min_periods=w).mean())
            if "alpha158_cntd" in factor_cfg:
                cntp = up_flags.rolling(w, min_periods=w).mean()
                cntn = down_flags.rolling(w, min_periods=w).mean()
                add_factor("alpha158_cntd", f"alpha158_cntd_{w}", cntp - cntn)
            if "alpha158_sump" in factor_cfg:
                add_factor("alpha158_sump", f"alpha158_sump_{w}", close_sum_diff / (close_abs_diff.rolling(w, min_periods=w).sum() + eps))
            if "alpha158_sumn" in factor_cfg:
                add_factor("alpha158_sumn", f"alpha158_sumn_{w}", close_sum_down / (close_abs_diff.rolling(w, min_periods=w).sum() + eps))
            if "alpha158_sumd" in factor_cfg:
                sumd = (close_sum_diff - close_sum_down) / (close_abs_diff.rolling(w, min_periods=w).sum() + eps)
                add_factor("alpha158_sumd", f"alpha158_sumd_{w}", sumd)
            if "alpha158_vma" in factor_cfg:
                add_factor("alpha158_vma", f"alpha158_vma_ratio_{w}", _safe_div(vol_mean, volume, eps))
            if "alpha158_vstd" in factor_cfg:
                add_factor(
                    "alpha158_vstd",
                    f"alpha158_vstd_ratio_{w}",
                    _safe_div(volume.rolling(w, min_periods=w).std(), volume, eps),
                )
            if "alpha158_wvma" in factor_cfg:
                vol_shock_mean = vol_price_shock.rolling(w, min_periods=w).mean()
                vol_shock_std = vol_price_shock.rolling(w, min_periods=w).std()
                add_factor("alpha158_wvma", f"alpha158_wvma_{w}", vol_shock_std / (vol_shock_mean + eps))
            if "alpha158_vsump" in factor_cfg:
                add_factor(
                    "alpha158_vsump",
                    f"alpha158_vsump_{w}",
                    volume_sum_up / (volume_abs_diff.rolling(w, min_periods=w).sum() + eps),
                )
            if "alpha158_vsumn" in factor_cfg:
                add_factor(
                    "alpha158_vsumn",
                    f"alpha158_vsumn_{w}",
                    volume_sum_down / (volume_abs_diff.rolling(w, min_periods=w).sum() + eps),
                )
            if "alpha158_vsumd" in factor_cfg:
                vsumd = (volume_sum_up - volume_sum_down) / (volume_abs_diff.rolling(w, min_periods=w).sum() + eps)
                add_factor("alpha158_vsumd", f"alpha158_vsumd_{w}", vsumd)

    if "flow_trade_count" in factor_cfg:
        p = factor_cfg["flow_trade_count"]["params"]
        for w in p.get("window", []):
            w = int(w)
            count_mean = count.rolling(w, min_periods=w).mean()
            add_factor("flow_trade_count", f"trade_count_zscore_{w}", _zscore(count, w, eps))
            add_factor("flow_trade_count", f"count_ma_ratio_{w}", _safe_div(count, count_mean, eps))
            add_factor("flow_trade_count", f"count_volatility_{w}", count.rolling(w, min_periods=w).std() / (count_mean + eps))

    avg_trade_size = volume / (count + eps)
    avg_quote_per_trade = quote_volume / (count + eps)
    if "flow_trade_size" in factor_cfg:
        p = factor_cfg["flow_trade_size"]["params"]
        add_factor("flow_trade_size", "avg_trade_size_raw", avg_trade_size)
        add_factor("flow_trade_size", "avg_quote_per_trade_raw", avg_quote_per_trade)
        for w in p.get("window", []):
            w = int(w)
            add_factor("flow_trade_size", f"avg_trade_size_zscore_{w}", _zscore(avg_trade_size, w, eps))
            add_factor("flow_trade_size", f"avg_quote_per_trade_zscore_{w}", _zscore(avg_quote_per_trade, w, eps))

    if "flow_taker_buy" in factor_cfg:
        p = factor_cfg["flow_taker_buy"]["params"]
        taker_buy_ratio = taker_buy_base / (volume + eps)
        taker_buy_count_proxy = taker_buy_base / (avg_trade_size + eps)
        taker_buy_imbalance = (2.0 * taker_buy_base - volume) / (volume + eps)
        taker_buy_quote_imbalance = (2.0 * taker_buy_quote - quote_volume) / (quote_volume + eps)
        add_factor("flow_taker_buy", "taker_buy_count_proxy_raw", taker_buy_count_proxy)
        add_factor("flow_taker_buy", "taker_buy_imbalance_raw", taker_buy_imbalance)
        add_factor("flow_taker_buy", "taker_buy_quote_imbalance_raw", taker_buy_quote_imbalance)
        for w in p.get("window", []):
            w = int(w)
            add_factor("flow_taker_buy", f"taker_buy_count_proxy_zscore_{w}", _zscore(taker_buy_count_proxy, w, eps))
            add_factor("flow_taker_buy", f"taker_buy_imbalance_ma_{w}", taker_buy_imbalance.rolling(w, min_periods=w).mean())
            add_factor(
                "flow_taker_buy",
                f"taker_buy_quote_imbalance_ma_{w}",
                taker_buy_quote_imbalance.rolling(w, min_periods=w).mean(),
            )
            add_factor(
                "flow_taker_buy",
                f"flow_surprise_{w}",
                taker_buy_ratio - taker_buy_ratio.rolling(w, min_periods=w).mean(),
            )

    if "liquidity_amihud" in factor_cfg:
        p = factor_cfg["liquidity_amihud"]["params"]
        illiq = ret1.abs() / (quote_volume + eps)
        add_factor("liquidity_amihud", "amihud_like_illiq_raw", illiq)
        for w in p.get("window", []):
            w = int(w)
            add_factor("liquidity_amihud", f"amihud_like_illiq_ma_{w}", illiq.rolling(w, min_periods=w).mean())
            add_factor("liquidity_amihud", f"amihud_like_illiq_zscore_{w}", _zscore(illiq, w, eps))

    if "liquidity_efficiency" in factor_cfg:
        p = factor_cfg["liquidity_efficiency"]["params"]
        price_range = (high - low).abs()
        ret_abs = ret1.abs()
        add_factor("liquidity_efficiency", "return_per_trade_raw", ret1 / (count + eps))
        add_factor("liquidity_efficiency", "range_per_trade_raw", price_range / (count + eps))
        add_factor("liquidity_efficiency", "range_per_quote_raw", price_range / (quote_volume + eps))
        add_factor("liquidity_efficiency", "price_volume_efficiency_volume_raw", ret_abs / (volume + eps))
        add_factor("liquidity_efficiency", "price_volume_efficiency_count_raw", ret_abs / (count + eps))
        for w in p.get("window", []):
            w = int(w)
            add_factor(
                "liquidity_efficiency",
                f"return_per_trade_ma_{w}",
                (ret1 / (count + eps)).rolling(w, min_periods=w).mean(),
            )
            add_factor(
                "liquidity_efficiency",
                f"range_per_trade_ma_{w}",
                (price_range / (count + eps)).rolling(w, min_periods=w).mean(),
            )
            add_factor(
                "liquidity_efficiency",
                f"range_per_quote_ma_{w}",
                (price_range / (quote_volume + eps)).rolling(w, min_periods=w).mean(),
            )
            add_factor(
                "liquidity_efficiency",
                f"price_volume_efficiency_volume_ma_{w}",
                (ret_abs / (volume + eps)).rolling(w, min_periods=w).mean(),
            )
            add_factor(
                "liquidity_efficiency",
                f"price_volume_efficiency_count_ma_{w}",
                (ret_abs / (count + eps)).rolling(w, min_periods=w).mean(),
            )

    if "alpha101_price_volume_rel" in factor_cfg:
        p = factor_cfg["alpha101_price_volume_rel"]["params"]
        for w in p.get("window", []):
            w = int(w)
            add_factor(
                "alpha101_price_volume_rel",
                f"alpha101_corr_close_log_volume_{w}",
                close.rolling(w, min_periods=w).corr(np.log1p(volume)),
            )
            add_factor(
                "alpha101_price_volume_rel",
                f"alpha101_corr_vwap_log_volume_{w}",
                vwap.rolling(w, min_periods=w).corr(np.log1p(volume)),
            )
            add_factor(
                "alpha101_price_volume_rel",
                f"alpha101_cov_ret_log_volume_{w}",
                ret1.rolling(w, min_periods=w).cov(np.log1p(volume)),
            )

    if "alpha101_delay_rank_decay" in factor_cfg:
        p = factor_cfg["alpha101_delay_rank_decay"]["params"]
        for w in p.get("rank_window", []):
            w = int(w)
            add_factor("alpha101_delay_rank_decay", f"alpha101_ts_rank_close_{w}", _rolling_rank_pct(close, w))
            add_factor("alpha101_delay_rank_decay", f"alpha101_ts_rank_volume_{w}", _rolling_rank_pct(volume, w))
        for d in p.get("delta_window", []):
            d = int(d)
            delta_close = close.diff(d)
            delta_vwap = vwap.diff(d)
            add_factor("alpha101_delay_rank_decay", f"alpha101_delta_close_{d}", _safe_div(delta_close, close, eps))
            add_factor("alpha101_delay_rank_decay", f"alpha101_delta_vwap_{d}", _safe_div(delta_vwap, vwap, eps))
            for decay_w in p.get("decay_window", []):
                decay_w = int(decay_w)
                add_factor(
                    "alpha101_delay_rank_decay",
                    f"alpha101_decay_delta_close_d{d}_w{decay_w}",
                    _decay_linear(_safe_div(delta_close, close, eps), decay_w),
                )
                add_factor(
                    "alpha101_delay_rank_decay",
                    f"alpha101_decay_delta_vwap_d{d}_w{decay_w}",
                    _decay_linear(_safe_div(delta_vwap, vwap, eps), decay_w),
                )

    if "alpha101_vwap_volatility" in factor_cfg:
        p = factor_cfg["alpha101_vwap_volatility"]["params"]
        for w in p.get("zscore_window", []):
            w = int(w)
            vwap_gap = _safe_div(close - vwap, close, eps)
            add_factor("alpha101_vwap_volatility", f"alpha101_vwap_gap_z_{w}", _zscore(vwap_gap, w, eps))
        for short_w in p.get("short_window", []):
            short_w = int(short_w)
            short_vol = log_ret.rolling(short_w, min_periods=short_w).std()
            short_range = tr.rolling(short_w, min_periods=short_w).mean()
            for long_w in p.get("long_window", []):
                long_w = int(long_w)
                if short_w >= long_w:
                    continue
                long_vol = log_ret.rolling(long_w, min_periods=long_w).std()
                long_range = tr.rolling(long_w, min_periods=long_w).mean()
                add_factor(
                    "alpha101_vwap_volatility",
                    f"alpha101_realized_vol_ratio_s{short_w}_l{long_w}",
                    short_vol / (long_vol + eps),
                )
                add_factor(
                    "alpha101_vwap_volatility",
                    f"alpha101_range_compression_s{short_w}_l{long_w}",
                    short_range / (long_range + eps),
                )

    out = pd.DataFrame(factor_values, index=df.index)
    metadata = pd.DataFrame(metadata_rows).drop_duplicates(subset=["factor"]).reset_index(drop=True)
    return out, metadata


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
    factor_cols = [c for c in merged_df.columns if c not in RESERVED_COLUMNS]
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


def _aggregate_rankings(rank_df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    if rank_df.empty:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for key, group in rank_df.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        row = dict(zip(group_cols, key))
        top = group.sort_values(by=["edge_vs_break_even", "auc_best", "samples"], ascending=[False, False, False]).iloc[0]
        row.update(
            {
                "n_factors": int(len(group)),
                "best_edge": float(group["edge_vs_break_even"].max()),
                "mean_edge": float(group["edge_vs_break_even"].mean()),
                "median_edge": float(group["edge_vs_break_even"].median()),
                "mean_auc": float(group["auc_best"].mean()),
                "positive_edge_ratio": float((group["edge_vs_break_even"] > 0.0).mean()),
                "top_factor": str(top["factor"]),
                "top_factor_edge": float(top["edge_vs_break_even"]),
                "top_factor_auc": float(top["auc_best"]),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def run_mining(cfg: MiningConfig) -> Dict[str, Any]:
    plan = load_plan(cfg.plan_path)
    status = str(plan.get("meta", {}).get("status", "proposed")).strip().lower()
    if status != "confirmed":
        raise ValueError("plan status must be confirmed before mining.")

    init_qlib(cfg.provider_uri)
    instruments = parse_instrument_list(cfg.provider_uri, cfg.instrument)
    merged_frames: List[pd.DataFrame] = []
    metadata_frames: List[pd.DataFrame] = []
    for instrument in instruments:
        base_df = fetch_base_frame(cfg, instrument=instrument)
        factor_df, factor_meta = compute_factors(base_df, plan, cfg.eps)
        merged_i = pd.concat(
            [
                base_df[["instrument", "datetime", "future_return", "target"]].reset_index(drop=True),
                factor_df.reset_index(drop=True),
            ],
            axis=1,
        )
        merged_frames.append(merged_i)
        metadata_frames.append(factor_meta)
    merged = pd.concat(merged_frames, ignore_index=True)
    factor_metadata = pd.concat(metadata_frames, ignore_index=True).drop_duplicates(subset=["factor"]).reset_index(drop=True)

    break_even = float(plan.get("meta", {}).get("objective", {}).get("break_even_winrate", 0.5882))
    rank_df = evaluate_factors(merged, break_even, cfg.eval_quantile, cfg.min_samples_per_factor)
    if not rank_df.empty and not factor_metadata.empty:
        rank_df = rank_df.merge(factor_metadata, on="factor", how="left")
        ordered_cols = [
            "factor",
            "plan_factor",
            "family",
            "source",
            "samples",
            "sign",
            "auc_best",
            "long_tail_n",
            "long_tail_winrate",
            "short_tail_n",
            "short_tail_winrate",
            "best_tail_winrate",
            "edge_vs_break_even",
            "status",
            "rationale",
        ]
        rank_df = rank_df[[c for c in ordered_cols if c in rank_df.columns]]

    rank_by_inst = []
    for instrument in instruments:
        sub = merged.loc[merged["instrument"] == instrument].copy()
        sub_rank = evaluate_factors(sub, break_even, cfg.eval_quantile, cfg.min_samples_per_factor)
        if sub_rank.empty:
            continue
        if not factor_metadata.empty:
            sub_rank = sub_rank.merge(factor_metadata, on="factor", how="left")
        sub_rank.insert(0, "instrument", instrument)
        rank_by_inst.append(sub_rank)
    rank_by_inst_df = pd.concat(rank_by_inst, ignore_index=True) if rank_by_inst else pd.DataFrame()

    source_summary = _aggregate_rankings(rank_df, ["source"])
    family_summary = _aggregate_rankings(rank_df, ["family"])
    plan_factor_summary = _aggregate_rankings(rank_df, ["plan_factor"])
    source_summary_by_inst = _aggregate_rankings(rank_by_inst_df, ["instrument", "source"])
    family_summary_by_inst = _aggregate_rankings(rank_by_inst_df, ["instrument", "family"])
    plan_factor_summary_by_inst = _aggregate_rankings(rank_by_inst_df, ["instrument", "plan_factor"])

    out_dir = Path(cfg.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out_dir / "factor_panel.parquet", index=False)
    factor_metadata.to_csv(out_dir / "factor_metadata.csv", index=False)
    rank_df.to_csv(out_dir / "factor_rankings.csv", index=False)
    rank_by_inst_df.to_csv(out_dir / "factor_rankings_by_instrument.csv", index=False)
    source_summary.to_csv(out_dir / "factor_source_summary.csv", index=False)
    family_summary.to_csv(out_dir / "factor_family_summary.csv", index=False)
    plan_factor_summary.to_csv(out_dir / "factor_plan_factor_summary.csv", index=False)
    source_summary_by_inst.to_csv(out_dir / "factor_source_summary_by_instrument.csv", index=False)
    family_summary_by_inst.to_csv(out_dir / "factor_family_summary_by_instrument.csv", index=False)
    plan_factor_summary_by_inst.to_csv(out_dir / "factor_plan_factor_summary_by_instrument.csv", index=False)

    summary = {
        "config": asdict(cfg),
        "plan_name": plan.get("meta", {}).get("plan_name"),
        "status": status,
        "n_instruments": len(instruments),
        "instruments": instruments,
        "n_rows": int(len(merged)),
        "n_factor_columns": int(max(0, merged.shape[1] - len(RESERVED_COLUMNS))),
        "n_ranked_factors": int(len(rank_df)),
        "n_ranked_factors_by_instrument": int(len(rank_by_inst_df)),
        "n_sources": int(source_summary["source"].nunique()) if not source_summary.empty else 0,
        "n_families": int(family_summary["family"].nunique()) if not family_summary.empty else 0,
        "top10": rank_df.head(10).to_dict(orient="records"),
        "source_summary": source_summary.to_dict(orient="records"),
        "family_summary": family_summary.head(20).to_dict(orient="records"),
        "output_dir": str(out_dir),
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    return summary
