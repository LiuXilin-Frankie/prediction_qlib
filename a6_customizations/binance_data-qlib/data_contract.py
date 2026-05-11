from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = PROJECT_ROOT / "a6_customizations" / "binance_data-qlib"
OFFICIAL_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)
OFFICIAL_SYMBOL_SET = set(OFFICIAL_SYMBOLS)
OFFICIAL_SOURCE_DIR = MODULE_DIR / "binance_data_1min"
OFFICIAL_CSV_DIR = MODULE_DIR / "csv_data_1min"
OFFICIAL_QLIB_DIR = MODULE_DIR / "qlib_data_1min"
OFFICIAL_MANIFEST_DIR = MODULE_DIR / "manifests" / "official_1min_6symbols"
REQUIRED_QLIB_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "count",
    "quote_volume",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "factor",
)


class DataContractError(RuntimeError):
    """Raised when data layers violate the agreed contract."""


def normalize_symbols(symbols: Sequence[str] | None) -> list[str]:
    raw_symbols = list(symbols) if symbols is not None else list(OFFICIAL_SYMBOLS)
    normalized: list[str] = []
    seen = set()
    for symbol in raw_symbols:
        symbol_text = str(symbol).strip().upper()
        if not symbol_text or symbol_text in seen:
            continue
        normalized.append(symbol_text)
        seen.add(symbol_text)
    if not normalized:
        raise ValueError("symbols 不能为空")
    if set(normalized) == OFFICIAL_SYMBOL_SET:
        return list(OFFICIAL_SYMBOLS)
    return normalized


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def ensure_partial_output_isolated(csv_path: Path, qlib_path: Path, symbols: Sequence[str]) -> None:
    symbol_set = set(symbols)
    is_partial_universe = symbol_set != OFFICIAL_SYMBOL_SET or len(symbols) != len(OFFICIAL_SYMBOLS)
    if same_path(qlib_path, OFFICIAL_QLIB_DIR) and is_partial_universe:
        raise ValueError(
            "禁止把局部 symbol 实验写入正式 qlib_data_1min。"
            " 若只转换部分 symbol，请显式指定独立的 --qlib_dir。"
        )
    if same_path(csv_path, OFFICIAL_CSV_DIR) and is_partial_universe:
        raise ValueError(
            "禁止把局部 symbol 实验复用正式 6-symbol 数据目录。"
            " 若只转换部分 symbol，请同时指定独立的 --csv_dir 与 --qlib_dir。"
        )


def validate_symbol_directories(source_path: Path, symbols: Sequence[str]) -> None:
    missing = [symbol for symbol in symbols if not (source_path / symbol).exists()]
    if missing:
        raise FileNotFoundError(
            f"source_dir 缺少以下 symbol 子目录: {missing}. "
            f"当前请求 symbols={list(symbols)}，source_dir={source_path}"
        )


def _timestamp_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_source_inventory(source_root: Path, expected_symbols: Sequence[str]) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    source_symbols = sorted(path.name for path in source_root.iterdir() if path.is_dir()) if source_root.exists() else []
    details: dict[str, Any] = {}
    missing = []
    for symbol in expected_symbols:
        symbol_dir = source_root / symbol
        if not symbol_dir.exists():
            missing.append(symbol)
            continue
        zip_files = sorted(symbol_dir.glob("*.zip"))
        if not zip_files:
            missing.append(symbol)
            details[symbol] = {
                "zip_dir": str(symbol_dir),
                "zip_count": 0,
                "zip_first": None,
                "zip_last": None,
            }
            continue
        details[symbol] = {
            "zip_dir": str(symbol_dir),
            "zip_count": len(zip_files),
            "zip_first": zip_files[0].stem[-10:],
            "zip_last": zip_files[-1].stem[-10:],
        }
    return {
        "path": str(source_root),
        "source_symbols": source_symbols,
        "missing_in_source": sorted(set(missing) | {symbol for symbol in expected_symbols if symbol not in source_symbols}),
        "source_details": details,
    }


def collect_parquet_inventory(parquet_root: Path, expected_symbols: Sequence[str]) -> dict[str, Any]:
    parquet_root = parquet_root.expanduser().resolve()
    parquet_symbols = sorted(path.stem for path in parquet_root.glob("*.parquet")) if parquet_root.exists() else []
    details: dict[str, Any] = {}
    missing = []
    for symbol in expected_symbols:
        parquet_path = parquet_root / f"{symbol}.parquet"
        if not parquet_path.exists():
            missing.append(symbol)
            continue
        date_df = pd.read_parquet(parquet_path, columns=["date"])
        date_df["date"] = pd.to_datetime(date_df["date"], errors="coerce")
        date_df = date_df.dropna(subset=["date"])
        if date_df.empty:
            missing.append(symbol)
            continue
        start = pd.Timestamp(date_df["date"].min())
        end = pd.Timestamp(date_df["date"].max())
        details[symbol] = {
            "path": str(parquet_path),
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "rows": int(len(date_df)),
        }
    return {
        "path": str(parquet_root),
        "parquet_symbols": parquet_symbols,
        "missing_in_parquet": sorted(set(missing) | {symbol for symbol in expected_symbols if symbol not in parquet_symbols}),
        "parquet_details": details,
    }


def _load_instruments(qlib_root: Path) -> dict[str, tuple[str, str]]:
    instruments_path = qlib_root / "instruments" / "all.txt"
    if not instruments_path.exists():
        return {}
    result: dict[str, tuple[str, str]] = {}
    for line in instruments_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise DataContractError(f"instruments/all.txt 格式异常: {line}")
        symbol, start, end = parts
        result[symbol] = (start, end)
    return result


def collect_qlib_inventory(qlib_root: Path, expected_symbols: Sequence[str], freq: str = "1min") -> dict[str, Any]:
    qlib_root = qlib_root.expanduser().resolve()
    instruments = _load_instruments(qlib_root) if qlib_root.exists() else {}
    qlib_symbols = sorted(instruments.keys())

    feature_root = qlib_root / "features"
    feature_symbols = sorted(path.name.upper() for path in feature_root.iterdir() if path.is_dir()) if feature_root.exists() else []
    missing_feature_fields: list[dict[str, Any]] = []
    for symbol in expected_symbols:
        symbol_feature_dir = feature_root / symbol.lower()
        if not symbol_feature_dir.exists():
            continue
        available_fields = {path.name.split(f".{freq}.bin")[0] for path in symbol_feature_dir.glob(f"*.{freq}.bin")}
        missing_fields = [field for field in REQUIRED_QLIB_FIELDS if field not in available_fields]
        if missing_fields:
            missing_feature_fields.append({"symbol": symbol, "missing_fields": missing_fields})

    calendar_path = qlib_root / "calendars" / f"{freq}.txt"
    calendar_rows = 0
    calendar_end = None
    if calendar_path.exists():
        lines = [line.strip() for line in calendar_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        calendar_rows = len(lines)
        if lines:
            calendar_end = lines[-1]

    return {
        "path": str(qlib_root),
        "qlib_symbols": qlib_symbols,
        "feature_symbols": feature_symbols,
        "unexpected_in_qlib": sorted([symbol for symbol in qlib_symbols if symbol not in expected_symbols]),
        "qlib_instrument_details": {
            symbol: {"start": start, "end": end} for symbol, (start, end) in instruments.items()
        },
        "calendar_rows": calendar_rows,
        "calendar_end": calendar_end,
        "missing_feature_fields": missing_feature_fields,
    }


def validate_data_contract(
    source_root: Path,
    parquet_root: Path,
    qlib_root: Path,
    expected_symbols: Sequence[str],
    freq: str = "1min",
    strict: bool = True,
) -> dict[str, Any]:
    expected = normalize_symbols(expected_symbols)
    source = collect_source_inventory(source_root, expected)
    parquet = collect_parquet_inventory(parquet_root, expected)
    qlib = collect_qlib_inventory(qlib_root, expected, freq=freq)

    summary: dict[str, Any] = {
        "status": "ok",
        "generated_at": _timestamp_now(),
        "expected_symbols": expected,
        **source,
        **parquet,
        **qlib,
        "missing_in_qlib": [],
        "time_mismatches": [],
    }

    max_symbol_end: pd.Timestamp | None = None
    for symbol in expected:
        parquet_info = summary["parquet_details"].get(symbol)
        qlib_info = summary["qlib_instrument_details"].get(symbol)
        if symbol not in summary["qlib_symbols"] or symbol not in summary["feature_symbols"]:
            summary["missing_in_qlib"].append(symbol)
        if parquet_info is None or qlib_info is None:
            continue
        if parquet_info["start"] != qlib_info["start"]:
            summary["time_mismatches"].append(
                {
                    "symbol": symbol,
                    "field": "start",
                    "parquet": parquet_info["start"],
                    "qlib_instrument": qlib_info["start"],
                }
            )
        if parquet_info["end"] != qlib_info["end"]:
            summary["time_mismatches"].append(
                {
                    "symbol": symbol,
                    "field": "end",
                    "parquet": parquet_info["end"],
                    "qlib_instrument": qlib_info["end"],
                }
            )
        current_end = pd.Timestamp(parquet_info["end"])
        max_symbol_end = current_end if max_symbol_end is None else max(max_symbol_end, current_end)

    calendar_end = summary["calendar_end"]
    if max_symbol_end is not None and calendar_end is not None and pd.Timestamp(calendar_end) < max_symbol_end:
        summary["time_mismatches"].append(
            {
                "symbol": "ALL",
                "field": "calendar_end",
                "expected_not_earlier_than": max_symbol_end.strftime("%Y-%m-%d %H:%M:%S"),
                "actual": calendar_end,
            }
        )

    summary["missing_in_qlib"] = sorted(set(summary["missing_in_qlib"]))
    has_errors = any(
        [
            summary["missing_in_source"],
            summary["missing_in_parquet"],
            summary["missing_in_qlib"],
            summary["unexpected_in_qlib"],
            summary["missing_feature_fields"],
            summary["time_mismatches"],
            summary["feature_symbols"] != sorted(expected),
            set(summary["qlib_symbols"]) != set(expected),
        ]
    )
    if has_errors:
        summary["status"] = "error"
        if strict:
            raise DataContractError(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
