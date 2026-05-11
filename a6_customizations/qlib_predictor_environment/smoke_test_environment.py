#!/usr/bin/env python3
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
A6 = ROOT / "a6_customizations"
BINANCE_DIR = A6 / "binance_data-qlib"
QLIB_DATA = BINANCE_DIR / "qlib_data_1min"
if str(BINANCE_DIR) not in sys.path:
    sys.path.insert(0, str(BINANCE_DIR))

from data_contract import OFFICIAL_CSV_DIR, OFFICIAL_SOURCE_DIR, OFFICIAL_SYMBOLS, validate_data_contract


def _load_module(name: str, path: Path, extra_paths: Iterable[Path] = ()) -> ModuleType:
    for extra_path in [ROOT, *extra_paths]:
        path_str = str(extra_path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _import_required_modules() -> dict[str, str]:
    module_names = [
        "numpy",
        "pandas",
        "pyarrow",
        "requests",
        "tqdm",
        "loguru",
        "yaml",
        "lightgbm",
        "xgboost",
        "qlib",
    ]
    versions: dict[str, str] = {}
    for module_name in module_names:
        module = importlib.import_module(module_name)
        versions[module_name] = str(getattr(module, "__version__", "ok"))
    return versions
def _check_data_contract() -> dict[str, object]:
    return validate_data_contract(
        source_root=OFFICIAL_SOURCE_DIR,
        parquet_root=OFFICIAL_CSV_DIR,
        qlib_root=QLIB_DATA,
        expected_symbols=OFFICIAL_SYMBOLS,
        freq="1min",
        strict=True,
    )


def _check_custom_entrypoints() -> dict[str, str]:
    results: dict[str, str] = {}

    _load_module(
        "a6_smoke_binance_downloader",
        BINANCE_DIR / "binance_data_downloader.py",
        [BINANCE_DIR],
    )
    _load_module(
        "a6_smoke_convert_binance",
        BINANCE_DIR / "convert_binance_zip_to_qlib.py",
        [BINANCE_DIR],
    )
    results["binance_data-qlib"] = "ok"

    baseline_dir = A6 / "qlib_btc_5min_baseline"
    _load_module("a6_smoke_baseline_data_handler", baseline_dir / "data_handler.py", [baseline_dir])
    baseline_experiment = _load_module(
        "a6_smoke_baseline_experiment",
        baseline_dir / "experiment.py",
        [baseline_dir],
    )
    cfg = baseline_experiment.BaselineConfig(provider_uri=str(QLIB_DATA), output_dir="/tmp/a6_smoke")
    cfg.resolved_model_params("lightgbm")
    cfg.resolved_model_params("xgboost")
    results["qlib_btc_5min_baseline"] = "ok"

    mining_dir = A6 / "qlib_btc_5min_factor_mining" / "scripts"
    _load_module("a6_smoke_factor_pipeline", mining_dir / "factor_mining_pipeline.py", [mining_dir])
    results["qlib_btc_5min_factor_mining"] = "ok"

    validation_dir = A6 / "qlib_ts_factor_validation_template" / "scripts"
    _load_module(
        "a6_smoke_ts_validation",
        validation_dir / "validate_timeseries_factors.py",
        [validation_dir],
    )
    results["qlib_ts_factor_validation_template"] = "ok"

    return results


def _check_factor_plan_render() -> dict[str, int | str]:
    cmd = [
        sys.executable,
        str(A6 / "qlib_btc_5min_factor_mining" / "scripts" / "run_factor_mining.py"),
        "--plan",
        str(A6 / "qlib_btc_5min_factor_mining" / "configs" / "factor_plan_tech_v1.yaml"),
        "--mode",
        "show-plan",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    return {
        "status": str(payload.get("status")),
        "factor_count": int(payload.get("factor_count", 0)),
    }


def main() -> None:
    try:
        summary = {
            "python": sys.version.split()[0],
            "dependency_versions": _import_required_modules(),
            "qlib_data": _check_data_contract(),
            "custom_entrypoints": _check_custom_entrypoints(),
            "factor_plan": _check_factor_plan_render(),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        message = str(exc)
        if message.startswith("{"):
            print(message)
            raise SystemExit(1)
        raise


if __name__ == "__main__":
    main()
