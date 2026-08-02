"""配置管理 — 全部从环境变量读取，绝不硬编码凭证。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _require(name: str) -> str:
    """读取必需环境变量，缺失时报清晰错误。"""
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"缺少必需环境变量: {name}")
    return value


@dataclass
class Config:
    """RidePulse 全局配置。

    所有字段均可通过环境变量覆盖，生产凭证绝不硬编码。
    """

    # -- 运行模式 --
    env: str = os.getenv("RIDEPULSE_ENV", "development")
    db_path: Path = Path(os.getenv("RIDEPULSE_DB_PATH", "data/ridepulse.db"))
    output_dir: Path = Path(os.getenv("RIDEPULSE_OUTPUT_DIR", "output"))

    # -- LLM --
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_primary_model: str = os.getenv("LLM_PRIMARY_MODEL", "")
    llm_review_model: str = os.getenv("LLM_REVIEW_MODEL", "")
    llm_evidence_model: str = os.getenv("LLM_EVIDENCE_MODEL", "")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # -- Embedding --
    embedding_mode: str = os.getenv("EMBEDDING_MODE", "api")  # api / local / fake
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "0") or "0")

    # -- 飞书 --
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_bitable_app_token: str = os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
    feishu_feedback_table_id: str = os.getenv("FEISHU_FEEDBACK_TABLE_ID", "")
    feishu_evidence_table_id: str = os.getenv("FEISHU_EVIDENCE_TABLE_ID", "")
    feishu_review_table_id: str = os.getenv("FEISHU_REVIEW_TABLE_ID", "")
    feishu_experiment_table_id: str = os.getenv("FEISHU_EXPERIMENT_TABLE_ID", "")

    @property
    def is_offline_test(self) -> bool:
        """是否为离线测试模式（无需外部服务）。"""
        return self.env == "test" or not self.llm_api_key

    @property
    def llm_configured(self) -> bool:
        """LLM API 是否已配置（可真实调用）。"""
        return bool(self.llm_base_url and self.llm_api_key and self.llm_primary_model)

    @property
    def feishu_configured(self) -> bool:
        """飞书是否已配置（可真实推送）。"""
        return bool(
            self.feishu_app_id
            and self.feishu_app_secret
            and self.feishu_bitable_app_token
        )

    @property
    def is_dual_model(self) -> bool:
        """是否使用不同模型做复判（可用于双模型文案声明）。"""
        return bool(
            self.llm_primary_model
            and self.llm_review_model
            and self.llm_primary_model != self.llm_review_model
        )

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.output_dir = Path(self.output_dir)


# 全局单例
_config: Config | None = None


def get_config() -> Config:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """注入配置（主要用于测试）。"""
    global _config
    _config = config
