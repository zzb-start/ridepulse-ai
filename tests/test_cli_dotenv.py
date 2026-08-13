"""CLI .env 加载测试 — .env 不在时跳过，存在时注入且不覆盖已有变量。"""

from __future__ import annotations

import os

from ridepulse.cli import _load_dotenv


def test_load_dotenv_sets_and_skips_existing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=http://example.com/v1\n"
        "LLM_API_KEY=sk-secret\n"
        "# 注释行不生效\n"
        "LLM_PRIMARY_MODEL=\"deepseek-v4-flash\"\n",
        encoding="utf-8",
    )
    os.environ["LLM_API_KEY"] = "already-set"
    try:
        _load_dotenv(str(env_file))
        assert os.environ["LLM_BASE_URL"] == "http://example.com/v1"
        assert os.environ["LLM_API_KEY"] == "already-set"  # 不覆盖
        assert os.environ["LLM_PRIMARY_MODEL"] == "deepseek-v4-flash"  # 去引号
    finally:
        os.environ.pop("LLM_BASE_URL", None)
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("LLM_PRIMARY_MODEL", None)


def test_load_dotenv_missing_file_is_noop(tmp_path):
    _load_dotenv(str(tmp_path / "nope.env"))  # 不应抛异常
