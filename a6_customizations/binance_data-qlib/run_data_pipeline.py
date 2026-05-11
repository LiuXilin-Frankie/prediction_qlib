#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR))

from binance_batch_downloader import BinanceBatchDownloader
from convert_binance_zip_to_qlib import run as convert_to_qlib
from data_contract import (
    OFFICIAL_MANIFEST_DIR,
    OFFICIAL_SYMBOLS,
    collect_parquet_inventory,
    collect_qlib_inventory,
    collect_source_inventory,
    normalize_symbols,
    validate_data_contract,
    write_json,
)


DEFAULT_CONFIG = MODULE_DIR / "configs" / "binance_1min_6symbols.yaml"


@dataclass
class PipelineConfig:
    name: str
    symbols: list[str]
    source_dir: Path
    csv_dir: Path
    qlib_dir: Path
    manifest_dir: Path
    start_date: str
    end_date: str | None
    publish_lag_days: int
    freq: str
    overwrite_mode: bool
    reuse_existing_parquet: bool
    enable_logging: bool

    def resolved_end_date(self) -> str:
        if self.end_date:
            return self.end_date
        lag_days = max(0, int(self.publish_lag_days))
        end = datetime.now().date() - timedelta(days=lag_days)
        return end.strftime("%Y-%m-%d")


def _load_pipeline_config(config_path: Path) -> PipelineConfig:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    symbols = normalize_symbols(payload.get("symbols") or list(OFFICIAL_SYMBOLS))
    module_root = config_path.resolve().parents[1]
    return PipelineConfig(
        name=str(payload.get("name", "binance_1min_pipeline")),
        symbols=symbols,
        source_dir=(module_root / payload.get("source_dir", "binance_data_1min")).resolve(),
        csv_dir=(module_root / payload.get("csv_dir", "csv_data_1min")).resolve(),
        qlib_dir=(module_root / payload.get("qlib_dir", "qlib_data_1min")).resolve(),
        manifest_dir=(module_root / payload.get("manifest_dir", str(OFFICIAL_MANIFEST_DIR.relative_to(module_root)))).resolve(),
        start_date=str(payload.get("start_date", "2024-01-01")),
        end_date=str(payload["end_date"]) if payload.get("end_date") else None,
        publish_lag_days=int(payload.get("publish_lag_days", 2)),
        freq=str(payload.get("freq", "1min")),
        overwrite_mode=bool(payload.get("overwrite_mode", False)),
        reuse_existing_parquet=bool(payload.get("reuse_existing_parquet", False)),
        enable_logging=bool(payload.get("enable_logging", True)),
    )


def _write_manifest_bundle(config: PipelineConfig, contract_summary: dict[str, Any], download_summary: dict[str, Any] | None = None) -> None:
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    common = {
        "generated_at": generated_at,
        "pipeline": config.name,
        "symbols": config.symbols,
        "freq": config.freq,
        "source_dir": str(config.source_dir),
        "csv_dir": str(config.csv_dir),
        "qlib_dir": str(config.qlib_dir),
    }
    raw_manifest = {
        **common,
        "download_summary": download_summary,
        "source_symbols": contract_summary["source_symbols"],
        "missing_in_source": contract_summary["missing_in_source"],
        "source_details": contract_summary["source_details"],
    }
    parquet_manifest = {
        **common,
        "parquet_symbols": contract_summary["parquet_symbols"],
        "missing_in_parquet": contract_summary["missing_in_parquet"],
        "parquet_details": contract_summary["parquet_details"],
    }
    qlib_manifest = {
        **common,
        "qlib_symbols": contract_summary["qlib_symbols"],
        "feature_symbols": contract_summary["feature_symbols"],
        "unexpected_in_qlib": contract_summary["unexpected_in_qlib"],
        "missing_in_qlib": contract_summary["missing_in_qlib"],
        "missing_feature_fields": contract_summary["missing_feature_fields"],
        "calendar_rows": contract_summary["calendar_rows"],
        "calendar_end": contract_summary["calendar_end"],
        "qlib_instrument_details": contract_summary["qlib_instrument_details"],
        "time_mismatches": contract_summary["time_mismatches"],
    }
    write_json(config.manifest_dir / "raw_zip_manifest.json", raw_manifest)
    write_json(config.manifest_dir / "parquet_manifest.json", parquet_manifest)
    write_json(config.manifest_dir / "qlib_manifest.json", qlib_manifest)
    write_json(config.manifest_dir / "contract_summary.json", {**common, **contract_summary})


def _validate_and_write_manifests(config: PipelineConfig, download_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    contract_summary = validate_data_contract(
        source_root=config.source_dir,
        parquet_root=config.csv_dir,
        qlib_root=config.qlib_dir,
        expected_symbols=config.symbols,
        freq=config.freq,
        strict=True,
    )
    _write_manifest_bundle(config, contract_summary, download_summary=download_summary)
    return contract_summary


def _run_download(config: PipelineConfig) -> dict[str, Any]:
    downloader = BinanceBatchDownloader(
        pairs=config.symbols,
        download_path=config.source_dir,
        start_date=config.start_date,
        end_date=config.resolved_end_date(),
        overwrite_mode=config.overwrite_mode,
        enable_logging=config.enable_logging,
    )
    download_summary = downloader.download_all()
    source_manifest = collect_source_inventory(config.source_dir, config.symbols)
    write_json(
        config.manifest_dir / "raw_zip_manifest.json",
        {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pipeline": config.name,
            "symbols": config.symbols,
            "start_date": config.start_date,
            "end_date": config.resolved_end_date(),
            "download_summary": download_summary,
            **source_manifest,
        },
    )
    return download_summary


def _run_convert(config: PipelineConfig) -> dict[str, Any]:
    convert_summary = convert_to_qlib(
        source_dir=str(config.source_dir),
        csv_dir=str(config.csv_dir),
        qlib_dir=str(config.qlib_dir),
        symbols=config.symbols,
        freq=config.freq,
        reuse_existing_parquet=config.reuse_existing_parquet,
    )
    parquet_manifest = collect_parquet_inventory(config.csv_dir, config.symbols)
    qlib_manifest = collect_qlib_inventory(config.qlib_dir, config.symbols, freq=config.freq)
    write_json(
        config.manifest_dir / "parquet_manifest.json",
        {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pipeline": config.name,
            **parquet_manifest,
            "convert_summary": convert_summary,
        },
    )
    write_json(
        config.manifest_dir / "qlib_manifest.json",
        {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pipeline": config.name,
            **qlib_manifest,
            "convert_summary": convert_summary,
        },
    )
    return convert_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standardized Binance 1min -> Qlib data pipeline")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="YAML config path")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=str(DEFAULT_CONFIG), help="YAML config path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("download", parents=[common])
    subparsers.add_parser("convert", parents=[common])
    subparsers.add_parser("validate", parents=[common])
    subparsers.add_parser("sync", parents=[common])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = _load_pipeline_config(config_path)

    download_summary: dict[str, Any] | None = None
    convert_summary: dict[str, Any] | None = None
    contract_summary: dict[str, Any] | None = None

    if args.command in {"download", "sync"}:
        download_summary = _run_download(config)
    if args.command in {"convert", "sync"}:
        convert_summary = _run_convert(config)
    if args.command in {"validate", "sync"}:
        contract_summary = _validate_and_write_manifests(config, download_summary=download_summary)

    payload = {
        "command": args.command,
        "config": asdict(config),
        "download_summary": download_summary,
        "convert_summary": convert_summary,
        "contract_summary": contract_summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
