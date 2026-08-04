"""Fail closed when files proposed for Git contain data, secrets, or unsafe exports."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 10 * 1024 * 1024

FORBIDDEN_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "backtest_results",
    "cache",
    "checkpoints",
    "credentials",
    "data",
    "datasets",
    "downloads",
    "historical_data",
    "logs",
    "market_data",
    "models",
    "orderbook",
    "output",
    "outputs",
    "private",
    "raw_data",
    "recovery",
    "results",
    "secrets",
    "temp",
    "ticks",
    "tmp",
    "venv",
}
FORBIDDEN_SUFFIXES = {
    ".arrow", ".bz2", ".ckpt", ".csv", ".db", ".duckdb", ".feather",
    ".gz", ".h5", ".hdf5", ".joblib", ".key", ".mat", ".npy", ".npz",
    ".onnx", ".p12", ".parquet", ".pem", ".pfx", ".pickle", ".pkl",
    ".pt", ".pth", ".sqlite", ".sqlite3", ".tar", ".tsv", ".xz", ".zip",
}
TEXT_SUFFIXES = {
    "", ".cfg", ".env", ".example", ".ini", ".json", ".md", ".py", ".ps1",
    ".sh", ".sql", ".toml", ".txt", ".yaml", ".yml",
}
SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("cloud access key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Bearer token", re.compile(rb"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.I)),
    ("credential in URL", re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^\s:/]+:[^\s/@]{8,}@")),
)
ASSIGNMENT = re.compile(
    rb"(?im)\b(api[_-]?key|secret|token|password|passwd|webhook)\b\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)
SAFE_LITERAL_MARKERS = (
    b"example", b"placeholder", b"dummy", b"invalid", b"changeme", b"<", b"${", b"$env:", b"os.environ",
)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def inside_git() -> bool:
    result = git("rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == b"true"


def normalize(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path escapes repository")
    return path.as_posix()


def candidate_paths(mode: str) -> list[str]:
    if mode == "staged":
        if not inside_git():
            raise RuntimeError("staged mode requires an initialized Git repository")
        raw = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").stdout
        return sorted({normalize(item.decode("utf-8", "surrogateescape")) for item in raw.split(b"\0") if item})
    if mode == "tracked":
        if not inside_git():
            raise RuntimeError("tracked mode requires an initialized Git repository")
        raw = git("ls-files", "-z").stdout
        return sorted({normalize(item.decode("utf-8", "surrogateescape")) for item in raw.split(b"\0") if item})
    if inside_git():
        raw = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
        return sorted({normalize(item.decode("utf-8", "surrogateescape")) for item in raw.split(b"\0") if item})
    paths: list[str] = []
    for directory, child_dirs, filenames in os.walk(ROOT, followlinks=False):
        current = Path(directory)
        relative_dir = current.relative_to(ROOT)
        if not relative_dir.parts:
            child_dirs[:] = [
                name
                for name in child_dirs
                if name.lower() not in FORBIDDEN_DIRS and name.lower() != ".git"
            ]
        elif relative_dir.parts[0].lower() == "artifacts":
            child_dirs[:] = [
                name
                for name in child_dirs
                if len(relative_dir.parts) == 1 and name.lower() == "registrations"
            ]
        else:
            child_dirs[:] = [name for name in child_dirs if name.lower() not in FORBIDDEN_DIRS]
        for filename in filenames:
            path = current / filename
            relative = path.relative_to(ROOT)
            if not ignored_before_init(relative):
                paths.append(relative.as_posix())
    return sorted(paths)


def ignored_before_init(relative: Path) -> bool:
    parts = {part.lower() for part in relative.parts[:-1]}
    name = relative.name.lower()
    if parts & FORBIDDEN_DIRS:
        return True
    if relative.parts and relative.parts[0].lower() == "artifacts":
        return not (
            len(relative.parts) == 3
            and relative.parts[1].lower() == "registrations"
            and relative.suffix.lower() == ".md"
        )
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return False


def staged_bytes(path: str) -> bytes:
    result = git("show", f":{path}", check=False)
    if result.returncode:
        raise RuntimeError(f"cannot read staged file: {path}")
    return result.stdout


def line_number(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def report(path: str, line: int | None, risk: str) -> None:
    location = f"{path}:{line}" if line is not None else path
    print(f"ERROR: {location} - {risk}")


def inspect_path(path: str, mode: str) -> int:
    errors = 0
    relative = PurePosixPath(path)
    lower_parts = {part.lower() for part in relative.parts[:-1]}
    suffix = relative.suffix.lower()
    name = relative.name.lower()

    if lower_parts & FORBIDDEN_DIRS or (relative.parts and relative.parts[0].lower() == "artifacts" and not (len(relative.parts) == 3 and relative.parts[1].lower() == "registrations" and suffix == ".md")):
        report(path, None, "forbidden directory")
        errors += 1
    if suffix in FORBIDDEN_SUFFIXES:
        report(path, None, "forbidden data, credential, archive, or model extension")
        errors += 1
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        report(path, None, "local environment file")
        errors += 1
    if re.search(r"(?:^|[._-])(credentials?|secrets?|api[_-]?keys?|tokens?)(?:[._-]|$)", name):
        report(path, None, "credential-like filename")
        errors += 1

    disk_path = ROOT / Path(*relative.parts)
    if mode != "staged" and disk_path.is_symlink():
        target = disk_path.resolve(strict=False)
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            report(path, None, "symbolic link points outside repository")
            errors += 1

    try:
        data = staged_bytes(path) if mode == "staged" else disk_path.read_bytes()
    except (OSError, RuntimeError) as exc:
        report(path, None, type(exc).__name__)
        return errors + 1
    if len(data) > MAX_BYTES:
        report(path, None, "file exceeds 10 MiB")
        errors += 1

    if suffix == ".ipynb":
        try:
            notebook = json.loads(data.decode("utf-8"))
            if any(cell.get("outputs") or cell.get("execution_count") is not None for cell in notebook.get("cells", [])):
                report(path, None, "Notebook contains output or execution state")
                errors += 1
        except (UnicodeDecodeError, json.JSONDecodeError):
            report(path, None, "invalid Notebook JSON")
            errors += 1

    if suffix not in TEXT_SUFFIXES and suffix != ".ipynb":
        return errors
    for risk, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(data):
            sample = match.group(0).lower()
            if risk == "credential in URL" and re.search(rb"\$[A-Za-z_]", sample):
                continue
            if any(marker.lower() in sample for marker in SAFE_LITERAL_MARKERS):
                continue
            report(path, line_number(data, match.start()), risk)
            errors += 1
    for match in ASSIGNMENT.finditer(data):
        value = match.group(2).lower()
        if any(marker.lower() in value for marker in SAFE_LITERAL_MARKERS):
            continue
        report(path, line_number(data, match.start()), "hard-coded credential-like literal")
        errors += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--worktree", action="store_true")
    group.add_argument("--staged", action="store_true")
    group.add_argument("--tracked", action="store_true")
    args = parser.parse_args()
    mode = "staged" if args.staged else "tracked" if args.tracked else "worktree"
    try:
        paths = candidate_paths(mode)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ERROR: repository - {type(exc).__name__}")
        return 2
    errors = sum(inspect_path(path, mode) for path in paths)
    print(f"Checked {len(paths)} {mode} file(s); risks={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
