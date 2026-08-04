"""Validate module development docs without third-party dependencies."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


MODULE_FILES = [
    "01-instruments.md",
    "02-market-data.md",
    "03-fundamentals.md",
    "04-universe.md",
    "05-features.md",
    "06-strategies.md",
    "07-portfolio.md",
    "08-signals.md",
    "09-execution-ledger.md",
    "10-backtest.md",
    "11-risk.md",
    "12-reporting.md",
    "13-api-ui.md",
    "14-platform-operations.md",
]

REQUIRED_HEADINGS = [
    "## 目标与边界",
    "## 所有数据",
    "## 接口契约",
    "## 业务规则",
    "## 失败、幂等与并发",
    "## 可观测与安全",
    "## 测试与验收",
    "## 不做事项",
]

BASELINE_HASHES = {
    "docs/01-requirements.md": "f023bab4bc20674c880b120a042339c377b376a26128035baf29a62a677d64ad",
    "docs/02-architecture.md": "2dab6ca2f3f5a4a7908069d2fa9f6ca9a1cccd6153ec4cab1ec2e96d8a113537",
    "docs/03-mvpselect-data-audit.md": "355398e2e50f49a195a980aa82dddfe6a732646739ee516586113ab3e40a195d",
    "docs/04-roadmap.md": "72ee57113cd2253ca891c892551d73de91fff938ef5a6718798b0322121fd85d",
    "docs/05-data-dictionary.md": "071ff400c125d4c2d0cec9b8ae7040565a6cd1ee435f193dc0886f5c931a625e",
}

REQUIRED_TEXT = {
    "docs/00-aligned-goal.md": ["ETF 择时和个股日频选股信号", "SELECT/KEEP/EXIT", "sleeve"],
    "docs/modules/03-fundamentals.md": ["available_at <= decision_at"],
    "docs/modules/04-universe.md": ["ETF_TIMING_POOL", "EQUITY_DAILY_POOL"],
    "docs/modules/05-features.md": ["ETF_TIMING", "EQUITY_DAILY_SELECTION"],
    "docs/modules/06-strategies.md": ["strategy_kind", "ETF_TIMING", "EQUITY_DAILY_SELECTION", "SELECT/KEEP/EXIT"],
    "docs/modules/07-portfolio.md": ["strategy_run_ids", "portfolio_sleeve_policy", "净目标"],
    "docs/modules/08-signals.md": ["signal_component", "SELECT/KEEP/EXIT", "净 recommendation", "instrument_id"],
    "docs/modules/09-execution-ledger.md": ["instrument_id", "fill/cash event"],
    "docs/modules/10-backtest.md": ["strategy_bundle", "下一可交易 bar", "instrument_id"],
    "docs/modules/11-risk.md": ["risk_scope", "COMBINED_ACCOUNT"],
    "docs/modules/12-reporting.md": ["sleeve_attribution", "SELECT/KEEP/EXIT"],
    "docs/modules/13-api-ui.md": ["daily-decisions", "instrument_id", "净 recommendation"],
    "docs/modules/14-platform-operations.md": [
        "RUN_ETF_DAILY_GATE",
        "RUN_EQUITY_DAILY_SELECTION",
        "BUILD_COMBINED_PORTFOLIO",
    ],
}

FORBIDDEN_TEXT = {
    "docs/00-aligned-goal.md": ["（猜的）"],
    "docs/modules/06-strategies.md": ["后续个股多因子", "首个闭环用 ETF"],
}

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
TIME_TOKENS = ("as_of", "decision_at", "effective", "business_date", "occurred_at", "时间", "日期", "时点")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    module_dir = root / "docs" / "modules"
    actual = sorted(path.name for path in module_dir.glob("[0-9][0-9]-*.md"))
    if actual != MODULE_FILES:
        errors.append(f"module files mismatch: expected {MODULE_FILES}, got {actual}")

    for name in MODULE_FILES:
        path = module_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        headings = {line.strip() for line in text.splitlines() if line.startswith("## ")}
        for heading in REQUIRED_HEADINGS:
            if heading not in headings:
                errors.append(f"{path.relative_to(root)} missing heading: {heading}")
        if not re.search(r"^## 主流程", text, flags=re.MULTILINE):
            errors.append(f"{path.relative_to(root)} missing main flow/state section")
        if "| Command |" not in text or "| Query |" not in text or "| Event |" not in text:
            errors.append(f"{path.relative_to(root)} missing command/query/event contracts")
        if "幂等" not in text:
            errors.append(f"{path.relative_to(root)} missing idempotency semantics")
        if "返回" not in text:
            errors.append(f"{path.relative_to(root)} missing explicit output semantics")
        if not any(token in text for token in TIME_TOKENS):
            errors.append(f"{path.relative_to(root)} missing time semantics")

    for relative, snippets in REQUIRED_TEXT.items():
        path = root / relative
        if not path.exists():
            errors.append(f"required specification missing: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                errors.append(f"{relative} missing required invariant: {snippet}")

    for relative, snippets in FORBIDDEN_TEXT.items():
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet in text:
                errors.append(f"{relative} contains obsolete scope: {snippet}")

    for relative, expected in BASELINE_HASHES.items():
        path = root / relative
        if not path.exists() or sha256(path) != expected:
            errors.append(f"baseline hash mismatch: {relative}")

    markdown_files = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    for path in markdown_files:
        if not path.exists():
            continue
        for target in LINK_RE.findall(path.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0]
            if not target or re.match(r"^[a-z]+://", target):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"broken link in {path.relative_to(root)}: {target}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("documentation validation: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("14 module docs: PASS")
    print("baseline hashes: PASS")
    print("links: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
