#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT_DIR = Path(__file__).resolve().parents[2]


def normalize_path(path_str: str) -> PurePosixPath:
    return PurePosixPath(path_str.replace("\\", "/"))


def blocked_reason(path_str: str) -> str | None:
    path = normalize_path(path_str)
    path_text = path.as_posix()

    if path.name == ".DS_Store":
        return "macOS metadata file"
    if "__pycache__" in path.parts:
        return "Python bytecode cache directory"
    if ".ipynb_checkpoints" in path.parts:
        return "Jupyter checkpoint directory"
    if path.name.endswith(".part"):
        return "partial download artifact"
    if path_text.startswith("a6_customizations/binance_data-qlib/binance_data_1min/"):
        return "raw Binance zip data should stay local"
    if path_text.startswith("a6_customizations/binance_data-qlib/csv_data_1min"):
        return "intermediate parquet data should stay local"
    if path_text.startswith("a6_customizations/binance_data-qlib/qlib_data_1min/features/"):
        return "generated Qlib feature binaries should stay local"
    if path_text.startswith("a6_customizations/") and "/outputs/" in f"/{path_text}" and path.suffix.lower() != ".json":
        return "non-JSON experiment outputs should stay local"
    return None


def strip_notebook_payload(notebook: dict) -> bool:
    changed = False
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            cell["outputs"] = []
            changed = True
        if cell.get("execution_count") is not None:
            cell["execution_count"] = None
            changed = True
    return changed


def dump_notebook(notebook: dict) -> bytes:
    return (json.dumps(notebook, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def load_notebook_bytes(raw_bytes: bytes) -> dict:
    return json.loads(raw_bytes.decode("utf-8"))


def clean_notebook_bytes(raw_bytes: bytes) -> bytes:
    notebook = load_notebook_bytes(raw_bytes)
    strip_notebook_payload(notebook)
    return dump_notebook(notebook)


def read_staged_file(path_str: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f":{path_str}"],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or f"unable to read staged file: {path_str}")
    return result.stdout


def command_clean_stdin(_: argparse.Namespace) -> int:
    sys.stdout.buffer.write(clean_notebook_bytes(sys.stdin.buffer.read()))
    return 0


def command_strip_notebook(args: argparse.Namespace) -> int:
    changed_paths: list[str] = []
    for raw_path in args.paths:
        path = (ROOT_DIR / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
        original = path.read_bytes()
        cleaned = clean_notebook_bytes(original)
        if cleaned != original:
            path.write_bytes(cleaned)
            changed_paths.append(str(path.relative_to(ROOT_DIR)))
    if changed_paths:
        for changed_path in changed_paths:
            print(f"stripped notebook outputs: {changed_path}")
    return 0


def command_check_paths(args: argparse.Namespace) -> int:
    blocked: list[tuple[str, str]] = []
    for path_str in args.paths:
        reason = blocked_reason(path_str)
        if reason:
            blocked.append((path_str, reason))
    if not blocked:
        return 0

    print("blocked staged files detected:", file=sys.stderr)
    for path_str, reason in blocked:
        print(f"  - {path_str}: {reason}", file=sys.stderr)
    return 1


def notebook_has_outputs(notebook: dict) -> bool:
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            return True
        if cell.get("execution_count") is not None:
            return True
    return False


def command_check_staged_notebooks(args: argparse.Namespace) -> int:
    dirty_paths: list[str] = []
    for path_str in args.paths:
        try:
            notebook = load_notebook_bytes(read_staged_file(path_str))
        except Exception as exc:  # pylint: disable=broad-except
            print(f"failed to inspect staged notebook {path_str}: {exc}", file=sys.stderr)
            return 1
        if notebook_has_outputs(notebook):
            dirty_paths.append(path_str)

    if not dirty_paths:
        return 0

    print("staged notebooks still contain outputs or execution counts:", file=sys.stderr)
    for path_str in dirty_paths:
        print(f"  - {path_str}", file=sys.stderr)
    print("run the repo hygiene setup so Git cleans notebooks on add/commit.", file=sys.stderr)
    return 1


def iter_git_files(include_untracked: bool) -> list[str]:
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT_DIR, check=True, capture_output=True, text=True).stdout.splitlines()
    if not include_untracked:
        return tracked
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return tracked + untracked


def command_scan(args: argparse.Namespace) -> int:
    files = iter_git_files(include_untracked=not args.tracked_only)
    blocked: list[tuple[str, str]] = []
    large_files: list[tuple[str, int]] = []

    for path_str in files:
        reason = blocked_reason(path_str)
        if reason:
            blocked.append((path_str, reason))
        path = ROOT_DIR / path_str
        if path.is_file():
            size = path.stat().st_size
            if size >= args.max_bytes:
                large_files.append((path_str, size))

    if blocked:
        print("tracked or untracked files that violate repo hygiene:")
        for path_str, reason in blocked:
            print(f"  - {path_str}: {reason}")

    if large_files:
        print(f"files larger than {args.max_bytes} bytes:")
        for path_str, size in sorted(large_files, key=lambda item: item[1], reverse=True):
            print(f"  - {path_str}: {size}")

    return 1 if blocked or large_files else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repository hygiene helpers for notebook and artifact management.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean_stdin_parser = subparsers.add_parser("clean-stdin", help="Strip notebook outputs from stdin and write the cleaned notebook to stdout.")
    clean_stdin_parser.set_defaults(func=command_clean_stdin)

    strip_notebook_parser = subparsers.add_parser("strip-notebook", help="Strip outputs and execution counts from notebook files in place.")
    strip_notebook_parser.add_argument("paths", nargs="+")
    strip_notebook_parser.set_defaults(func=command_strip_notebook)

    check_paths_parser = subparsers.add_parser("check-paths", help="Reject staged files that match blocked generated-artifact patterns.")
    check_paths_parser.add_argument("paths", nargs="*")
    check_paths_parser.set_defaults(func=command_check_paths)

    check_staged_notebooks_parser = subparsers.add_parser(
        "check-staged-notebooks",
        help="Verify the staged versions of notebooks are already stripped.",
    )
    check_staged_notebooks_parser.add_argument("paths", nargs="*")
    check_staged_notebooks_parser.set_defaults(func=command_check_staged_notebooks)

    scan_parser = subparsers.add_parser("scan", help="Scan the repo for blocked files and large tracked artifacts.")
    scan_parser.add_argument("--tracked-only", action="store_true")
    scan_parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    scan_parser.set_defaults(func=command_scan)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
