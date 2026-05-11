import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    p
    for p in sys.path
    if Path(p or ".").resolve() not in {PROJECT_ROOT, SCRIPT_DIR.parent.parent}
]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qlib
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

from data_handler import BTC5MinAlpha158


_QLIB_INITIALIZED = False


@dataclass
class BaselineConfig:
    provider_uri: str
    instrument: str = "BTCUSDT"
    freq: str = "1min"
    model_type: str = "auto"
    train_days: int = 90
    valid_days: int = 7
    test_days: int = 7
    retrain_days: int = 7
    sample_minutes: int = 5
    entry_offset_minutes: int = 1
    horizon_minutes: int = 5
    flat_epsilon: float = 1e-12
    min_valid_trades: int = 5
    threshold_start: float = 0.55
    threshold_end: float = 0.80
    threshold_step: float = 0.01
    payout_win: float = 3.5
    payout_loss: float = 5.0
    random_state: int = 42
    experiment_start: Optional[str] = None
    experiment_end: Optional[str] = None
    output_dir: str = "a6_customizations/qlib_btc_5min_baseline/outputs/latest"
    model_params: Optional[Dict] = None
    external_factor_panels: Optional[List[str]] = None
    train_low_abs_quantile: float = 0.0
    train_low_abs_drop_fraction: float = 0.0

    def resolved_model_params(self, backend: str) -> Dict:
        if backend == "lightgbm":
            default_params = {
                "objective": "binary",
                "n_estimators": 1000,
                "learning_rate": 0.05,
                "num_leaves": 31,
                "max_depth": -1,
                "min_child_samples": 200,
                "subsample": 0.8,
                "subsample_freq": 1,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.0,
                "reg_lambda": 2.0,
                "random_state": self.random_state,
                "n_jobs": -1,
                "verbosity": -1,
            }
        elif backend == "xgboost":
            default_params = {
                "objective": "binary:logistic",
                "n_estimators": 1000,
                "learning_rate": 0.05,
                "max_depth": 6,
                "min_child_weight": 5,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.0,
                "reg_lambda": 2.0,
                "random_state": self.random_state,
                "n_jobs": -1,
                "tree_method": "hist",
                "eval_metric": "logloss",
            }
        else:
            raise ValueError(f"Unsupported model backend: {backend}")

        if self.model_params:
            default_params.update(self.model_params)
        return default_params


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


def get_instrument_range(provider_uri: str, instrument: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    inst_path = Path(provider_uri).resolve() / "instruments" / "all.txt"
    inst_df = pd.read_csv(
        inst_path,
        sep="\t",
        header=None,
        names=["instrument", "start_time", "end_time"],
    )
    row = inst_df.loc[inst_df["instrument"] == instrument]
    if row.empty:
        raise ValueError(f"Instrument {instrument} not found in {inst_path}")
    start_time = pd.Timestamp(row.iloc[0]["start_time"])
    end_time = pd.Timestamp(row.iloc[0]["end_time"])
    return start_time, end_time


def build_dataset(
    config: BaselineConfig,
    train_seg: Tuple[pd.Timestamp, pd.Timestamp],
    valid_seg: Tuple[pd.Timestamp, pd.Timestamp],
    test_seg: Tuple[pd.Timestamp, pd.Timestamp],
) -> DatasetH:
    handler_end = test_seg[1] + pd.Timedelta(
        minutes=config.entry_offset_minutes + config.horizon_minutes
    )
    handler = BTC5MinAlpha158(
        instruments=[config.instrument],
        start_time=train_seg[0],
        end_time=handler_end,
        fit_start_time=train_seg[0],
        fit_end_time=train_seg[1],
        freq=config.freq,
        entry_offset_minutes=config.entry_offset_minutes,
        horizon_minutes=config.horizon_minutes,
    )
    return DatasetH(
        handler=handler,
        segments={
            "train": train_seg,
            "valid": valid_seg,
            "test": test_seg,
        },
    )


def _get_datetime_level(index: pd.Index) -> pd.Index:
    if isinstance(index, pd.MultiIndex):
        if "datetime" in index.names:
            return index.get_level_values("datetime")
        return index.get_level_values(-1)
    return index


def _flatten_segment_frame(df: pd.DataFrame) -> pd.DataFrame:
    feature_df = df["feature"].copy()
    label_series = df["label"].iloc[:, 0].rename("future_return")
    flat_df = feature_df.copy()
    flat_df["future_return"] = label_series
    return flat_df


def _sanitize_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [col for col in df.columns if col != "future_return"]
    if numeric_cols:
        df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
    return df


def prepare_segment(
    dataset: DatasetH,
    segment: str,
    sample_minutes: int,
    flat_epsilon: float,
    drop_flat: bool,
) -> pd.DataFrame:
    raw_df = dataset.prepare(
        segment,
        col_set=["feature", "label"],
        data_key=DataHandlerLP.DK_L,
    )
    if raw_df.empty:
        return pd.DataFrame()

    df = _sanitize_numeric_frame(_flatten_segment_frame(raw_df))
    dt_index = _get_datetime_level(df.index)
    sample_mask = (dt_index.minute % sample_minutes == 0) & (dt_index.second == 0)
    df = df.loc[sample_mask].copy()
    if df.empty:
        return df

    df["is_flat"] = df["future_return"].abs() <= flat_epsilon
    df["target"] = (df["future_return"] > flat_epsilon).astype(int)
    if drop_flat:
        df = df.loc[~df["is_flat"]].copy()
    return df


def _sanitize_panel_name(path: str) -> str:
    return Path(path).stem.replace(".", "_").replace("-", "_")


def load_external_factor_frames(panel_paths: Optional[List[str]], instrument: str) -> List[Tuple[str, pd.DataFrame]]:
    if not panel_paths:
        return []

    external_frames: List[Tuple[str, pd.DataFrame]] = []
    for idx, panel_path in enumerate(panel_paths):
        panel_file = Path(panel_path).resolve()
        if not panel_file.exists():
            raise FileNotFoundError(f"External factor panel not found: {panel_file}")

        panel_df = pd.read_parquet(panel_file)
        if "datetime" not in panel_df.columns:
            raise ValueError(f"Panel missing 'datetime' column: {panel_file}")

        if "instrument" in panel_df.columns:
            panel_df = panel_df.loc[panel_df["instrument"] == instrument].copy()

        factor_cols = [
            col
            for col in panel_df.columns
            if col not in {"instrument", "datetime", "future_return", "target"}
        ]
        if not factor_cols:
            continue

        frame = panel_df[["datetime"] + factor_cols].copy()
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        frame = frame.drop_duplicates(subset=["datetime"], keep="last").set_index("datetime").sort_index()
        frame = frame.replace([np.inf, -np.inf], np.nan)

        prefix = f"ext{idx+1}_{_sanitize_panel_name(panel_path)}"
        frame = frame.rename(columns={col: f"{prefix}__{col}" for col in factor_cols})
        external_frames.append((prefix, frame))

    return external_frames


def augment_with_external_factors(
    segment_df: pd.DataFrame,
    external_frames: List[Tuple[str, pd.DataFrame]],
) -> pd.DataFrame:
    if segment_df.empty or not external_frames:
        return segment_df

    out = segment_df.copy()
    dt_index = pd.to_datetime(_get_datetime_level(out.index))
    for _, ext_frame in external_frames:
        aligned = ext_frame.reindex(dt_index)
        for col in aligned.columns:
            out[col] = aligned[col].to_numpy()
    return out


def maybe_random_drop_low_abs_train_samples(
    train_df: pd.DataFrame,
    low_abs_quantile: float,
    drop_fraction: float,
) -> pd.DataFrame:
    if train_df.empty:
        return train_df
    if low_abs_quantile <= 0.0 or drop_fraction <= 0.0:
        return train_df

    q = float(np.clip(low_abs_quantile, 0.0, 1.0))
    frac = float(np.clip(drop_fraction, 0.0, 1.0))
    if q == 0.0 or frac == 0.0:
        return train_df

    abs_ret = train_df["future_return"].abs()
    threshold = float(abs_ret.quantile(q))
    low_abs_idx = train_df.index[abs_ret <= threshold]
    n_low = len(low_abs_idx)
    if n_low == 0:
        return train_df

    n_drop = int(n_low * frac)
    if n_drop <= 0:
        return train_df
    if n_drop >= n_low:
        n_drop = n_low - 1
    if n_drop <= 0:
        return train_df

    drop_idx = np.random.choice(np.arange(n_low), size=n_drop, replace=False)
    drop_labels = low_abs_idx[drop_idx]
    return train_df.drop(index=drop_labels)


def generate_rolling_windows(
    config: BaselineConfig,
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
) -> List[Dict]:
    experiment_start = pd.Timestamp(config.experiment_start) if config.experiment_start else data_start
    experiment_end = pd.Timestamp(config.experiment_end) if config.experiment_end else data_end

    cursor = experiment_start
    windows = []
    window_id = 0

    while True:
        train_start = cursor
        train_end = train_start + pd.Timedelta(days=config.train_days) - pd.Timedelta(minutes=1)
        valid_start = train_end + pd.Timedelta(minutes=1)
        valid_end = valid_start + pd.Timedelta(days=config.valid_days) - pd.Timedelta(minutes=1)
        test_start = valid_end + pd.Timedelta(minutes=1)
        test_end = test_start + pd.Timedelta(days=config.test_days) - pd.Timedelta(minutes=1)
        label_safe_end = test_end + pd.Timedelta(
            minutes=config.entry_offset_minutes + config.horizon_minutes
        )

        if label_safe_end > experiment_end:
            break

        windows.append(
            {
                "window_id": window_id,
                "train": (train_start, train_end),
                "valid": (valid_start, valid_end),
                "test": (test_start, test_end),
            }
        )
        window_id += 1
        cursor = cursor + pd.Timedelta(days=config.retrain_days)

    return windows


def _max_drawdown(trade_pnl: pd.Series) -> float:
    if trade_pnl.empty:
        return 0.0
    equity = trade_pnl.cumsum()
    drawdown = equity - equity.cummax()
    return float(-drawdown.min())


def _longest_losing_streak(trade_pnl: pd.Series) -> int:
    longest = 0
    current = 0
    for pnl in trade_pnl:
        if pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def simulate_trades(
    scored_df: pd.DataFrame,
    upper_threshold: float,
    config: BaselineConfig,
) -> Tuple[pd.DataFrame, Dict]:
    lower_threshold = 1.0 - upper_threshold
    trades = []
    next_available_entry = pd.Timestamp.min

    for row in scored_df.sort_values("decision_time").itertuples():
        score = float(row.score)
        if score >= upper_threshold:
            signal = 1
        elif score <= lower_threshold:
            signal = -1
        else:
            signal = 0

        if signal == 0:
            continue

        entry_time = row.decision_time + pd.Timedelta(minutes=config.entry_offset_minutes)
        if entry_time < next_available_entry:
            continue

        settlement_time = entry_time + pd.Timedelta(minutes=config.horizon_minutes)
        next_available_entry = settlement_time

        if signal == 1 and row.future_return > config.flat_epsilon:
            pnl = config.payout_win
            is_win = 1
        elif signal == -1 and row.future_return < -config.flat_epsilon:
            pnl = config.payout_win
            is_win = 1
        else:
            pnl = -config.payout_loss
            is_win = 0

        trades.append(
            {
                "decision_time": row.decision_time,
                "entry_time": entry_time,
                "settlement_time": settlement_time,
                "score": score,
                "signal": signal,
                "future_return": float(row.future_return),
                "is_flat": int(row.is_flat),
                "is_win": is_win,
                "pnl": pnl,
            }
        )

    trade_df = pd.DataFrame(trades)
    metrics = compute_trade_metrics(trade_df)
    metrics["upper_threshold"] = float(upper_threshold)
    metrics["lower_threshold"] = float(lower_threshold)
    return trade_df, metrics


def compute_trade_metrics(trade_df: pd.DataFrame) -> Dict:
    if trade_df.empty:
        return {
            "n_trades": 0,
            "win_rate": np.nan,
            "avg_pnl": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "longest_losing_streak": 0,
        }

    trade_pnl = trade_df["pnl"]
    return {
        "n_trades": int(len(trade_df)),
        "win_rate": float(trade_df["is_win"].mean()),
        "avg_pnl": float(trade_pnl.mean()),
        "total_pnl": float(trade_pnl.sum()),
        "max_drawdown": _max_drawdown(trade_pnl),
        "longest_losing_streak": _longest_losing_streak(trade_pnl),
    }


def build_scored_frame(segment_df: pd.DataFrame, scores: np.ndarray) -> pd.DataFrame:
    scored_df = segment_df[["future_return", "is_flat"]].copy()
    scored_df["score"] = scores
    scored_df["decision_time"] = _get_datetime_level(scored_df.index)
    return scored_df.reset_index()


def select_threshold(
    valid_scored: pd.DataFrame,
    config: BaselineConfig,
) -> Dict:
    candidates = np.arange(
        config.threshold_start,
        config.threshold_end + config.threshold_step / 2,
        config.threshold_step,
    )

    evaluations = []
    for upper_threshold in candidates:
        trade_df, metrics = simulate_trades(valid_scored, float(upper_threshold), config)
        metrics["trade_df"] = trade_df
        evaluations.append(metrics)

    eligible = [m for m in evaluations if m["n_trades"] >= config.min_valid_trades]
    pool = eligible if eligible else evaluations
    best = max(
        pool,
        key=lambda item: (
            item["total_pnl"],
            item["avg_pnl"],
            -item["max_drawdown"],
            item["win_rate"] if not np.isnan(item["win_rate"]) else -1.0,
            item["n_trades"],
        ),
    )
    return best


def _fit_lightgbm(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    config: BaselineConfig,
) -> object:
    import lightgbm as lgb

    x_train = train_df.drop(columns=["future_return", "is_flat", "target"])
    y_train = train_df["target"]

    valid_non_flat = valid_df.loc[~valid_df["is_flat"]].copy()
    if valid_non_flat.empty:
        raise ValueError("Validation segment has no non-flat samples for early stopping.")

    x_valid = valid_non_flat.drop(columns=["future_return", "is_flat", "target"])
    y_valid = valid_non_flat["target"]

    if y_train.nunique() < 2:
        raise ValueError("Training segment contains only one class after filtering flat samples.")
    if y_valid.nunique() < 2:
        raise ValueError("Validation segment contains only one class after filtering flat samples.")

    model = lgb.LGBMClassifier(**config.resolved_model_params("lightgbm"))
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        eval_metric="binary_logloss",
        callbacks=[
            lgb.early_stopping(50),
            lgb.log_evaluation(50),
        ],
    )
    return model


def _fit_xgboost(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    config: BaselineConfig,
) -> object:
    import inspect

    from xgboost import XGBClassifier

    x_train = train_df.drop(columns=["future_return", "is_flat", "target"])
    y_train = train_df["target"]

    valid_non_flat = valid_df.loc[~valid_df["is_flat"]].copy()
    if valid_non_flat.empty:
        raise ValueError("Validation segment has no non-flat samples for early stopping.")

    x_valid = valid_non_flat.drop(columns=["future_return", "is_flat", "target"])
    y_valid = valid_non_flat["target"]

    if y_train.nunique() < 2:
        raise ValueError("Training segment contains only one class after filtering flat samples.")
    if y_valid.nunique() < 2:
        raise ValueError("Validation segment contains only one class after filtering flat samples.")

    model = XGBClassifier(**config.resolved_model_params("xgboost"))
    fit_kwargs = {
        "eval_set": [(x_valid, y_valid)],
        "verbose": False,
    }
    if "early_stopping_rounds" in inspect.signature(model.fit).parameters:
        fit_kwargs["early_stopping_rounds"] = 50
    elif "early_stopping_rounds" not in model.get_params():
        model.set_params(early_stopping_rounds=50)

    model.fit(x_train, y_train, **fit_kwargs)
    return model


def train_model(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    config: BaselineConfig,
) -> Tuple[object, str]:
    backends = []
    if config.model_type == "auto":
        backends = ["lightgbm", "xgboost"]
    else:
        backends = [config.model_type]

    errors = {}
    for backend in backends:
        try:
            if backend == "lightgbm":
                return _fit_lightgbm(train_df, valid_df, config), backend
            if backend == "xgboost":
                return _fit_xgboost(train_df, valid_df, config), backend
            raise ValueError(f"Unsupported model type: {backend}")
        except Exception as exc:
            errors[backend] = str(exc)

    raise RuntimeError(f"All candidate model backends failed: {errors}")


def run_single_window(
    config: BaselineConfig,
    window: Dict,
    external_frames: Optional[List[Tuple[str, pd.DataFrame]]] = None,
) -> Tuple[Dict, pd.DataFrame]:
    dataset = build_dataset(config, window["train"], window["valid"], window["test"])
    train_df = prepare_segment(dataset, "train", config.sample_minutes, config.flat_epsilon, drop_flat=True)
    valid_df = prepare_segment(dataset, "valid", config.sample_minutes, config.flat_epsilon, drop_flat=False)
    test_df = prepare_segment(dataset, "test", config.sample_minutes, config.flat_epsilon, drop_flat=False)

    if external_frames:
        train_df = augment_with_external_factors(train_df, external_frames)
        valid_df = augment_with_external_factors(valid_df, external_frames)
        test_df = augment_with_external_factors(test_df, external_frames)

    # Optional augmentation for training only: randomly drop part of low-abs-return samples.
    train_df = maybe_random_drop_low_abs_train_samples(
        train_df,
        low_abs_quantile=config.train_low_abs_quantile,
        drop_fraction=config.train_low_abs_drop_fraction,
    )

    if train_df.empty or valid_df.empty or test_df.empty:
        raise ValueError(f"Window {window['window_id']} has empty segment after preparation.")

    model, model_backend = train_model(train_df, valid_df, config)

    feature_cols = [col for col in train_df.columns if col not in {"future_return", "is_flat", "target"}]
    valid_scores = model.predict_proba(valid_df[feature_cols])[:, 1]
    test_scores = model.predict_proba(test_df[feature_cols])[:, 1]

    valid_scored = build_scored_frame(valid_df, valid_scores)
    test_scored = build_scored_frame(test_df, test_scores)

    best_threshold = select_threshold(valid_scored, config)
    test_trade_df, test_metrics = simulate_trades(test_scored, best_threshold["upper_threshold"], config)

    feature_importance = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    best_iteration = 0
    if hasattr(model, "best_iteration_") and model.best_iteration_ is not None:
        best_iteration = int(model.best_iteration_)
    elif hasattr(model, "best_iteration") and model.best_iteration is not None:
        best_iteration = int(model.best_iteration)

    window_metrics = {
        "window_id": window["window_id"],
        "model_backend": model_backend,
        "train_start": window["train"][0],
        "train_end": window["train"][1],
        "valid_start": window["valid"][0],
        "valid_end": window["valid"][1],
        "test_start": window["test"][0],
        "test_end": window["test"][1],
        "train_samples": int(len(train_df)),
        "valid_samples": int(len(valid_df)),
        "test_samples": int(len(test_df)),
        "best_iteration": best_iteration,
        "valid_threshold": float(best_threshold["upper_threshold"]),
        "valid_n_trades": int(best_threshold["n_trades"]),
        "valid_win_rate": best_threshold["win_rate"],
        "valid_avg_pnl": best_threshold["avg_pnl"],
        "valid_total_pnl": best_threshold["total_pnl"],
        "test_n_trades": int(test_metrics["n_trades"]),
        "test_win_rate": test_metrics["win_rate"],
        "test_avg_pnl": test_metrics["avg_pnl"],
        "test_total_pnl": test_metrics["total_pnl"],
        "test_max_drawdown": test_metrics["max_drawdown"],
        "test_longest_losing_streak": test_metrics["longest_losing_streak"],
        "top_feature_1": feature_importance.index[0] if not feature_importance.empty else None,
        "top_feature_1_importance": float(feature_importance.iloc[0]) if not feature_importance.empty else np.nan,
    }

    if not test_trade_df.empty:
        test_trade_df["window_id"] = window["window_id"]
    return window_metrics, test_trade_df


def summarize_results(window_metrics_df: pd.DataFrame, trade_log_df: pd.DataFrame) -> Dict:
    overall = compute_trade_metrics(trade_log_df)
    summary = {
        "n_windows": int(len(window_metrics_df)),
        "n_test_trades": overall["n_trades"],
        "overall_win_rate": overall["win_rate"],
        "overall_avg_pnl": overall["avg_pnl"],
        "overall_total_pnl": overall["total_pnl"],
        "overall_max_drawdown": overall["max_drawdown"],
        "overall_longest_losing_streak": overall["longest_losing_streak"],
    }

    if not window_metrics_df.empty:
        summary["avg_test_win_rate_by_window"] = float(window_metrics_df["test_win_rate"].mean())
        summary["avg_test_trades_by_window"] = float(window_metrics_df["test_n_trades"].mean())
    return summary


def save_results(
    config: BaselineConfig,
    window_metrics_df: pd.DataFrame,
    trade_log_df: pd.DataFrame,
    summary: Dict,
) -> Path:
    output_dir = Path(config.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    window_metrics_df.to_csv(output_dir / "window_metrics.csv", index=False)
    trade_log_df.to_csv(output_dir / "trade_log.csv", index=False)
    with open(output_dir / "summary.json", "w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2, default=str, ensure_ascii=False)
    with open(output_dir / "config.json", "w", encoding="utf-8") as fp:
        json.dump(asdict(config), fp, indent=2, default=str, ensure_ascii=False)
    return output_dir


def run_walk_forward(config: BaselineConfig) -> Dict:
    init_qlib(config.provider_uri)
    data_start, data_end = get_instrument_range(config.provider_uri, config.instrument)
    windows = generate_rolling_windows(config, data_start, data_end)
    if not windows:
        raise ValueError("No rolling windows generated. Please check the date range and window sizes.")

    external_frames = load_external_factor_frames(config.external_factor_panels, config.instrument)

    metrics_records = []
    trade_logs = []

    for window in windows:
        metrics, trade_df = run_single_window(config, window, external_frames=external_frames)
        metrics_records.append(metrics)
        if not trade_df.empty:
            trade_logs.append(trade_df)

    window_metrics_df = pd.DataFrame(metrics_records)
    trade_log_df = pd.concat(trade_logs, ignore_index=True) if trade_logs else pd.DataFrame()
    summary = summarize_results(window_metrics_df, trade_log_df)
    summary["external_factor_panels"] = [str(Path(p).resolve()) for p in (config.external_factor_panels or [])]
    summary["n_external_factor_panels"] = int(len(config.external_factor_panels or []))
    summary["n_external_factor_columns"] = int(sum(frame.shape[1] for _, frame in external_frames))
    output_dir = save_results(config, window_metrics_df, trade_log_df, summary)
    summary["output_dir"] = str(output_dir)
    return summary
