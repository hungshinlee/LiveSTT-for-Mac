"""文件與程式是否同步。

掛在測試裡，這樣改了 CLI 卻忘記更新文件時，跑 pytest 就會發現，
不必記得另外執行 scripts/check_docs.py。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_docs  # noqa: E402


@pytest.fixture(scope="module")
def docs():
    readme = check_docs.README.read_text(encoding="utf-8")
    return readme, readme + check_docs.CLAUDE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def flags():
    return [
        f
        for f in check_docs.cli_flags(check_docs.cli_help())
        if f not in check_docs.FOREIGN_FLAGS
    ]


@pytest.mark.parametrize("title,check", check_docs.CHECKS, ids=[t for t, _ in check_docs.CHECKS])
def test_documentation_is_in_sync(title, check, flags, docs):
    readme, combined = docs
    problems = check(flags, readme, combined)

    assert not problems, f"{title}：\n  " + "\n  ".join(problems)
