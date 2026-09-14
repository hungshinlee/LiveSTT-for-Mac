#!/usr/bin/env python3
"""檢查文件與程式是否同步。

新增功能時很容易忘記更新文件，或是文件寫的預設值跟程式對不上。
這支腳本把這些比對自動化：

    uv run python scripts/check_docs.py

有任何不一致就以非零狀態結束，方便掛進 CI 或 pre-commit。
"""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

README = ROOT / "README.md"
CLAUDE = ROOT / "CLAUDE.md"

#: 這些不是本專案 CLI 的旗標，出現在文件裡是別的工具的用法
FOREIGN_FLAGS = {
    "--force", "--dtype", "--output-dir", "--cask",
    "--no-build-isolation", "--local-dir",
}

#: 表格裡代表「沒有預設值」的描述性文字
NO_DEFAULT = {
    "", "無", "自動偵測", "系統預設", "依引擎", "系統字體", "不翻譯", "不輸出",
}


def cli_help() -> str:
    return subprocess.run(
        [sys.executable, "-m", "livestt.cli", "--help"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout


def cli_flags(help_text: str) -> list[str]:
    """從 --help 抽出所有長選項。"""
    return sorted({m for m in re.findall(r"^\s+(--[a-z][a-z-]+)", help_text, re.M)})


def section(md: str, title: str, until: str) -> str:
    try:
        return md[md.index(f"## {title}") : md.index(f"## {until}")]
    except ValueError:
        return ""


def slug(heading: str) -> str:
    return re.sub(r"[^\w一-鿿-]", "", heading.strip().lower().replace(" ", "-"))


# ---- 各項檢查 --------------------------------------------------------------


def check_flags_documented(flags, docs) -> list[str]:
    return [f"選項 {f} 沒有出現在任何文件中" for f in flags if f not in docs]


def check_flags_in_table(flags, readme) -> list[str]:
    table = section(readme, "完整參數表", "轉換自訂模型")
    if not table:
        return ["找不到「完整參數表」章節"]
    return [f"選項 {f} 未列入完整參數表" for f in flags if f not in table]


def check_defaults(readme) -> list[str]:
    """比對表格裡寫的預設值與 argparse 的實際預設值。"""
    from livestt.cli import build_parser

    actual = {
        action.option_strings[0]: action.default
        for action in build_parser()._actions
        if action.option_strings
    }

    problems = []
    table = section(readme, "完整參數表", "轉換自訂模型")
    for block in table.split("\n\n"):
        header = next((ln for ln in block.splitlines() if ln.startswith("|")), "")
        if "預設" not in header:
            continue  # 這張表沒有預設值欄位（例如查詢類）
        for line in block.splitlines():
            match = re.match(r"^\|\s*`(--[a-z-]+)`\s*\|(.*)\|\s*$", line)
            if not match:
                continue
            flag, rest = match.groups()
            documented = rest.split("|")[-1].strip().strip("`")
            if flag not in actual:
                problems.append(f"{flag} 出現在參數表，但 CLI 沒有這個選項")
                continue
            value = actual[flag]
            if value is None or documented in NO_DEFAULT:
                continue
            expected = "關閉" if value is False else str(value)
            if documented != expected:
                problems.append(
                    f"{flag} 的預設值不一致：文件寫 {documented!r}，程式是 {expected!r}"
                )
    return problems


def check_modules_listed(docs) -> list[str]:
    problems = []
    for path in sorted((ROOT / "livestt").rglob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.name not in docs:
            problems.append(f"模組 {path.name} 未出現在專案結構中")
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name not in docs:
            problems.append(f"測試檔 {path.name} 未出現在文件中")
    return problems


def check_known_models(readme) -> list[str]:
    from livestt import postprocess, translate
    from livestt.engines import ENGINES, qwen_mlx, whisper_mlx

    problems = []
    for name in ENGINES:
        if f"`{name}`" not in readme:
            problems.append(f"引擎 {name} 未出現在 README")
    for repo, *_ in [*whisper_mlx.KNOWN_MODELS, *qwen_mlx.KNOWN_MODELS,
                     *translate.KNOWN_MODELS]:
        if repo not in readme:
            problems.append(f"模型 {repo} 未出現在 README")
    for config in postprocess.CONFIGS:
        if f"`{config}`" not in readme:
            problems.append(f"OpenCC 配置 {config} 未出現在 README")
    return problems


def check_links(docs) -> list[str]:
    headings = {slug(h) for h in re.findall(r"^##+ (.+)$", docs, re.M)}
    problems = [
        f"錨點 #{anchor} 找不到對應的標題"
        for anchor in set(re.findall(r"\]\(#([^)]+)\)", docs))
        if anchor not in headings
    ]
    problems += [
        f"連結指向不存在的檔案：{target}"
        for target in set(re.findall(r"\]\((?!#|https?:|mailto:)([^)]+)\)", docs))
        if not (ROOT / target).exists()
    ]
    return problems


def check_examples_parse(docs) -> list[str]:
    from livestt.cli import build_parser

    parser = build_parser()
    problems = []
    for command in re.findall(r"^\s*(?:uv run )?livestt (.+)$", docs.replace("\\\n", " "), re.M):
        command = command.split("#")[0].strip()
        # 含 shell 管線或純 --help 的範例不走 argparse
        if not command or "|" in command or command == "--help":
            continue
        try:
            parser.parse_args(shlex.split(command))
        except SystemExit:
            problems.append(f"範例指令無法解析：livestt {command}")
    return problems


CHECKS = [
    ("所有選項都有文件", lambda f, r, d: check_flags_documented(f, d)),
    ("所有選項列入參數表", lambda f, r, d: check_flags_in_table(f, r)),
    ("預設值與程式一致", lambda f, r, d: check_defaults(r)),
    ("模組與測試檔已列出", lambda f, r, d: check_modules_listed(d)),
    ("引擎與模型已記載", lambda f, r, d: check_known_models(r)),
    ("連結有效", lambda f, r, d: check_links(d)),
    ("範例指令可解析", lambda f, r, d: check_examples_parse(d)),
]


def main() -> int:
    readme = README.read_text(encoding="utf-8")
    docs = readme + CLAUDE.read_text(encoding="utf-8")
    flags = [f for f in cli_flags(cli_help()) if f not in FOREIGN_FLAGS]

    print(f"檢查文件（CLI 共 {len(flags)} 個選項）\n")
    total = 0
    for title, check in CHECKS:
        problems = check(flags, readme, docs)
        total += len(problems)
        print(f"  {'✅' if not problems else '❌'} {title}")
        for problem in problems:
            print(f"       {problem}")

    print()
    if total:
        print(f"發現 {total} 個問題")
        return 1
    print("文件與程式同步")
    return 0


if __name__ == "__main__":
    sys.exit(main())
