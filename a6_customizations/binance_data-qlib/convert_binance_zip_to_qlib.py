import io
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List

import pandas as pd
from loguru import logger

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

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
    if all(isinstance(c, (int, float)) for c in df.columns):
        df.columns = DEFAULT_COLUMNS[: df.shape[1]]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _pick_column(df: pd.DataFrame, candidates: Iterable[str], fallback_index: int) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    return df.columns[fallback_index]


def _parse_datetime(series: pd.Series) -> pd.Series:
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
    df = _normalize_columns(df)
    time_col = _pick_column(df, ["open_time", "open_timestamp", "timestamp", "time"], 0)
    open_col = _pick_column(df, ["open"], 1)
    high_col = _pick_column(df, ["high"], 2)
    low_col = _pick_column(df, ["low"], 3)
    close_col = _pick_column(df, ["close"], 4)
    volume_col = _pick_column(df, ["volume"], 5)

    dt = _parse_datetime(df[time_col])
    out = pd.DataFrame(
        {
            "symbol": symbol,
            "date": dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": pd.to_numeric(df[volume_col], errors="coerce"),
            "factor": 1.0,
        }
    )
    return out.dropna(subset=["date"])


def _collect_zip_files(source_dir: Path) -> List[Path]:
    return sorted(source_dir.glob("*.zip"))


def build_csv_from_zips(source_dir: Path, output_csv: Path, symbol: str) -> Path:
    zip_files = _collect_zip_files(source_dir)
    if not zip_files:
        raise FileNotFoundError(f"未找到zip文件: {source_dir}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    wrote_header = False
    for zip_path in zip_files:
        df = _read_zip_csv(zip_path)
        if df.empty:
            continue
        qlib_df = _build_qlib_dataframe(df, symbol)
        if qlib_df.empty:
            continue
        qlib_df.to_csv(output_csv, mode="a", header=not wrote_header, index=False)
        wrote_header = True
    if not output_csv.exists():
        raise RuntimeError("未生成有效的CSV文件")
    return output_csv


def dump_qlib(csv_dir: Path, qlib_dir: Path, freq: str) -> None:
    dumper = DumpDataAll(
        csv_path=str(csv_dir),
        qlib_dir=str(qlib_dir),
        freq=freq,
        include_fields="open,close,high,low,volume,factor",
        symbol_field_name="symbol",
        date_field_name="date",
    )
    dumper.dump()


def run(
    source_dir: str = "a6_customizations/binance_data-qlib/binance_data_1min/BTCUSDT",
    csv_dir: str = "a6_customizations/binance_data-qlib/csv_data_1min",
    qlib_dir: str = "a6_customizations/binance_data-qlib/qlib_data_1min",
    symbol: str = "BTCUSDT",
    freq: str = "1min",
) -> None:
    source_path = Path(source_dir).expanduser().resolve()
    csv_path = Path(csv_dir).expanduser().resolve()
    qlib_path = Path(qlib_dir).expanduser().resolve()
    logger.info(f"开始转换: {source_path}")
    output_csv = build_csv_from_zips(source_path, csv_path / f"{symbol}.csv", symbol)
    logger.info(f"CSV已生成: {output_csv}")
    dump_qlib(csv_path, qlib_path, freq)
    logger.info(f"Qlib数据已生成: {qlib_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source_dir", default="a6_customizations/binance_data-qlib/binance_data_1min/BTCUSDT")
    parser.add_argument("--csv_dir", default="a6_customizations/binance_data-qlib/csv_data_1min")
    parser.add_argument("--qlib_dir", default="a6_customizations/binance_data-qlib/qlib_data_1min")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--freq", default="1min")
    args = parser.parse_args()
    run(
        source_dir=args.source_dir,
        csv_dir=args.csv_dir,
        qlib_dir=args.qlib_dir,
        symbol=args.symbol,
        freq=args.freq,
    )
