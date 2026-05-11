from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd
from loguru import logger

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_contract import (
    OFFICIAL_SYMBOLS,
    ensure_partial_output_isolated,
    normalize_symbols,
    validate_symbol_directories,
)
from scripts.dump_bin import DumpDataAll


DEFAULT_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def _read_zip_csv(zip_path: Path) -> pd.DataFrame:
    """
    读取zip中的CSV文件并返回DataFrame

    参数：
        zip_path (Path): zip文件路径

    返回：
        pd.DataFrame: 读取到的数据
    """
    with zipfile.ZipFile(zip_path) as zf:
        members = [name for name in zf.namelist() if not name.endswith("/")]
        if not members:
            return pd.DataFrame()
        data = zf.read(members[0])
    buffer = io.BytesIO(data)
    df = pd.read_csv(buffer, header=None, low_memory=False)
    if df.empty:
        return df
    first_row = df.iloc[0].astype(str).str.lower().tolist()
    header_like = sum(any(k in v for k in ["open", "high", "low", "close", "time", "volume"]) for v in first_row)
    if header_like >= 3:
        buffer.seek(0)
        df = pd.read_csv(buffer, header=0, low_memory=False)
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    规范化列名并按默认列填充

    参数：
        df (pd.DataFrame): 原始数据

    返回：
        pd.DataFrame: 列名标准化后的数据
    """
    if all(isinstance(c, (int, float)) for c in df.columns):
        df.columns = DEFAULT_COLUMNS[: df.shape[1]]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _pick_column(df: pd.DataFrame, candidates: Iterable[str], fallback_index: int) -> str:
    """
    从候选列名中选择可用列

    参数：
        df (pd.DataFrame): 数据
        candidates (Iterable[str]): 候选列名
        fallback_index (int): 兜底列索引

    返回：
        str: 选中的列名
    """
    for col in candidates:
        if col in df.columns:
            return col
    return df.columns[fallback_index]


def _parse_datetime(series: pd.Series) -> pd.Series:
    """
    解析时间列为datetime格式

    参数：
        series (pd.Series): 时间列

    返回：
        pd.Series: 解析后的时间序列
    """
    if pd.api.types.is_numeric_dtype(series):
        max_val = series.dropna().max()
        if pd.isna(max_val):
            return pd.to_datetime(series, errors="coerce")
        if max_val > 10**12:
            dt = pd.to_datetime(series, unit="ms", utc=True, errors="coerce")
        elif max_val > 10**10:
            dt = pd.to_datetime(series, unit="s", utc=True, errors="coerce")
        else:
            dt = pd.to_datetime(series, utc=True, errors="coerce")
    else:
        dt = pd.to_datetime(series, utc=True, errors="coerce")
    return dt.dt.tz_convert(None)


def _build_qlib_dataframe(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    构建符合Qlib规范的DataFrame

    参数：
        df (pd.DataFrame): 原始数据
        symbol (str): 交易对名称

    返回：
        pd.DataFrame: Qlib格式数据
    """
    df = _normalize_columns(df)
    time_col = _pick_column(df, ["open_time", "open_timestamp", "timestamp", "time"], 0)
    open_col = _pick_column(df, ["open"], 1)
    high_col = _pick_column(df, ["high"], 2)
    low_col = _pick_column(df, ["low"], 3)
    close_col = _pick_column(df, ["close"], 4)
    volume_col = _pick_column(df, ["volume"], 5)
    quote_volume_col = _pick_column(df, ["quote_volume"], 7)
    count_col = _pick_column(df, ["count"], 8)
    taker_buy_volume_col = _pick_column(df, ["taker_buy_volume"], 9)
    taker_buy_quote_volume_col = _pick_column(df, ["taker_buy_quote_volume"], 10)

    dt = _parse_datetime(df[time_col])
    volume = pd.to_numeric(df[volume_col], errors="coerce")
    quote_volume = pd.to_numeric(df[quote_volume_col], errors="coerce")
    vwap = quote_volume.div(volume.replace(0, np.nan))
    close = pd.to_numeric(df[close_col], errors="coerce")
    # When volume is zero or missing, fall back to close to avoid invalid VWAP.
    vwap = vwap.fillna(close)
    out = pd.DataFrame(
        {
            "symbol": symbol,
            "date": dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": close,
            "volume": volume,
            "quote_volume": quote_volume,
            "vwap": vwap,
            "count": pd.to_numeric(df[count_col], errors="coerce"),
            "taker_buy_volume": pd.to_numeric(df[taker_buy_volume_col], errors="coerce"),
            "taker_buy_quote_volume": pd.to_numeric(df[taker_buy_quote_volume_col], errors="coerce"),
            "factor": 1.0,
        }
    )
    return out.dropna(subset=["date"])


def _ensure_vwap_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "vwap" in df.columns:
        df["vwap"] = pd.to_numeric(df["vwap"], errors="coerce")
        return df
    if "quote_volume" not in df.columns or "volume" not in df.columns:
        raise ValueError("Parquet缺少 `quote_volume` 或 `volume`，无法补算 VWAP")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["quote_volume"] = pd.to_numeric(df["quote_volume"], errors="coerce")
    df["vwap"] = df["quote_volume"].div(df["volume"].replace(0, np.nan)).fillna(df["close"])
    return df

def _collect_zip_files(source_dir: Path) -> List[Path]:
    """
    收集目录下全部zip文件

    参数：
        source_dir (Path): 目录路径

    返回：
        List[Path]: zip文件列表
    """
    return sorted(source_dir.glob("*.zip"))


def build_csv_from_zips(source_dir: Path, output_csv: Path, symbol: str) -> Path:
    """
    顺序读取zip并生成合并后的Parquet文件

    参数：
        source_dir (Path): zip目录
        output_csv (Path): 目标文件路径（后缀将改为parquet）
        symbol (str): 交易对名称

    返回：
        Path: 生成的Parquet路径
    """
    zip_files = _collect_zip_files(source_dir)
    if not zip_files:
        raise FileNotFoundError(f"未找到zip文件: {source_dir}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for zip_path in zip_files:
        df = _read_zip_csv(zip_path)
        if df.empty:
            continue
        qlib_df = _build_qlib_dataframe(df, symbol)
        if not qlib_df.empty:
            frames.append(qlib_df)
    if not frames:
        raise RuntimeError("未生成有效的CSV文件")
    merged = pd.concat(frames, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["date"]).sort_values("date")
    parquet_path = output_csv.with_suffix(".parquet")
    merged.to_parquet(parquet_path, index=False)
    return parquet_path


def _resolve_symbol_source_dir(base_dir: Path, symbol: str) -> Path:
    """
    解析symbol对应的数据目录

    参数：
        base_dir (Path): 数据根目录
        symbol (str): 交易对名称

    返回：
        Path: 最终使用的数据目录
    """
    candidate = base_dir / symbol
    if not candidate.exists():
        raise FileNotFoundError(f"未找到 symbol 目录: {candidate}")
    return candidate


def _collect_calendar_and_instruments(
    parquet_paths: List[Path],
    symbols: List[str],
    dumper: DumpDataAll,
) -> tuple[List[pd.Timestamp], List[str]]:
    """
    汇总日历与合约信息

    参数：
        parquet_paths (List[Path]): parquet路径列表
        symbols (List[str]): 交易对列表
        dumper (DumpDataAll): Qlib转储器

    返回：
        tuple[List[pd.Timestamp], List[str]]: 日历列表与合约信息
    """
    all_dates = set()
    instruments = []
    for parquet_path, symbol in zip(parquet_paths, symbols):
        date_df = pd.read_parquet(parquet_path, columns=["date"])
        date_df["date"] = pd.to_datetime(date_df["date"], errors="coerce")
        date_df = date_df.dropna(subset=["date"])
        if date_df.empty:
            raise RuntimeError(f"{symbol} Parquet文件为空，无法转储Qlib数据")
        all_dates.update(date_df["date"].tolist())
        begin_time = dumper._format_datetime(date_df["date"].min())
        end_time = dumper._format_datetime(date_df["date"].max())
        instruments.append(f"{symbol.upper()}{dumper.INSTRUMENTS_SEP}{begin_time}{dumper.INSTRUMENTS_SEP}{end_time}")
    calendars = sorted(map(pd.Timestamp, all_dates))
    return calendars, instruments


def dump_qlib(parquet_paths: List[Path], qlib_dir: Path, freq: str, symbols: List[str]) -> None:
    """
    将Parquet数据写入Qlib格式目录

    参数：
        parquet_paths (List[Path]): parquet路径列表
        qlib_dir (Path): Qlib数据目录
        freq (str): 数据频率
        symbols (List[str]): 交易对列表
    """
    dumper = DumpDataAll(
        csv_path=str(parquet_paths[0].parent),
        qlib_dir=str(qlib_dir),
        freq=freq,
        include_fields="open,close,high,low,volume,vwap,factor,quote_volume,count,taker_buy_volume,taker_buy_quote_volume",
        symbol_field_name="symbol",
        date_field_name="date",
    )
    calendars, instruments = _collect_calendar_and_instruments(parquet_paths, symbols, dumper)
    dumper.save_calendars(calendars)
    dumper.save_instruments(instruments)
    for parquet_path, symbol in zip(parquet_paths, symbols):
        df = _ensure_vwap_column(pd.read_parquet(parquet_path))
        df.to_parquet(parquet_path, index=False)
        df["symbol"] = symbol
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        dumper._dump_bin(df, calendars)


def run(
    source_dir: str = "a6_customizations/binance_data-qlib/binance_data_1min",
    csv_dir: str = "a6_customizations/binance_data-qlib/csv_data_1min",
    qlib_dir: str = "a6_customizations/binance_data-qlib/qlib_data_1min",
    symbols: List[str] = None,
    freq: str = "1min",
    reuse_existing_parquet: bool = True,
) -> dict[str, object]:
    """
    批量转换多个交易对数据到Qlib格式

    参数：
        source_dir (str): zip数据目录
        csv_dir (str): 中间parquet输出目录
        qlib_dir (str): Qlib输出目录
        symbols (List[str]): 交易对列表
        freq (str): 数据频率
        reuse_existing_parquet (bool): 若中间Parquet已存在，则直接复用并补算VWAP
    """
    source_path = Path(source_dir).expanduser().resolve()
    csv_path = Path(csv_dir).expanduser().resolve()
    qlib_path = Path(qlib_dir).expanduser().resolve()
    symbols = normalize_symbols(symbols)
    ensure_partial_output_isolated(csv_path, qlib_path, symbols)
    validate_symbol_directories(source_path, symbols)
    parquet_paths = []
    for symbol in symbols:
        output_parquet = csv_path / f"{symbol}.parquet"
        if reuse_existing_parquet and output_parquet.exists():
            logger.info(f"复用现有Parquet并补算VWAP: {output_parquet}")
            df = _ensure_vwap_column(pd.read_parquet(output_parquet))
            df.to_parquet(output_parquet, index=False)
        else:
            symbol_source_path = _resolve_symbol_source_dir(source_path, symbol)
            logger.info(f"开始转换: {symbol_source_path}")
            output_parquet = build_csv_from_zips(symbol_source_path, output_parquet, symbol)
            logger.info(f"Parquet已生成: {output_parquet}")
        parquet_paths.append(output_parquet)
    dump_qlib(parquet_paths, qlib_path, freq, symbols)
    logger.info(f"Qlib数据已生成: {qlib_path}")
    return {
        "symbols": symbols,
        "source_dir": str(source_path),
        "csv_dir": str(csv_path),
        "qlib_dir": str(qlib_path),
        "freq": freq,
        "reuse_existing_parquet": reuse_existing_parquet,
        "parquet_paths": [str(path) for path in parquet_paths],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source_dir", default="a6_customizations/binance_data-qlib/binance_data_1min")
    parser.add_argument("--csv_dir", default="a6_customizations/binance_data-qlib/csv_data_1min")
    parser.add_argument("--qlib_dir", default="a6_customizations/binance_data-qlib/qlib_data_1min")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT",
        help="逗号分隔的多个symbol；正式 qlib_data_1min 约定为固定 6-symbol",
    )
    parser.add_argument("--freq", default="1min")
    parser.add_argument("--reuse_existing_parquet", action="store_true", default=False)
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    run(
        source_dir=args.source_dir,
        csv_dir=args.csv_dir,
        qlib_dir=args.qlib_dir,
        symbols=symbols,
        freq=args.freq,
        reuse_existing_parquet=args.reuse_existing_parquet,
    )


"""
python a6_customizations/binance_data-qlib/convert_binance_zip_to_qlib.py \
  --source_dir a6_customizations/binance_data-qlib/binance_data_1min \
  --csv_dir a6_customizations/binance_data-qlib/csv_data_1min \
  --qlib_dir a6_customizations/binance_data-qlib/qlib_data_1min \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT \
  --freq 1min
"""
