"""配置管理 — 全部从环境变量读取，绝不硬编码凭证。

默认指向 OpenAI 官方端点与 GPT-6 系列：分类用 Luna、复判用 Sol、证据卡用 Astra。
只换 LLM_BASE_URL / 模型名即可接其他 OpenAI 兼容端点，代码零改动。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# OpenAI 官方端点（GPT-6 系列默认走这里）
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# 默认模型分层：
#   luna  — 单条分类量大、结构固定，用低成本档跑量
#   sol   — 复判必须与首轮不同模型，且要独立判断能力
#   astra — 证据卡是长上下文综合 + 引用约束，用旗舰档
DEFAULT_PRIMARY_MODEL = "gpt-6-luna"
DEFAULT_REVIEW_MODEL = "gpt-6-sol"
DEFAULT_EVIDENCE_MODEL = "gpt-6-astra"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_EMBEDDING_DIMENSION = 3072

# 推理强度同样按阶段配：分类量大用 low，复判要判断力用 medium，
# 证据卡直接对外输出用 high。LLM_REASONING_EFFORT 一填即全局覆盖。
DEFAULT_REASONING_EFFORT = {"classify": "low", "review": "medium", "evidence": "high"}


def _require(name: str) -> str:
    """读取必需环境变量，缺失时报清晰错误。"""
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"缺少必需环境变量: {name}")
    return value


# 字符串字段 -> (环境变量名, 类默认值)。
# dataclass 默认值在 import 时固化，.env 加载晚于 import，
# 因此字段值为类默认值时，须在实例化时重新从环境变量（含 .env 注入的）读取。
_STR_ENV_KEYS = {
    "env": ("RIDEPULSE_ENV", "development"),
    "db_path": ("RIDEPULSE_DB_PATH", "data/ridepulse.db"),
    "output_dir": ("RIDEPULSE_OUTPUT_DIR", "output"),
    "llm_base_url": ("LLM_BASE_URL", DEFAULT_OPENAI_BASE_URL),
    "llm_api_key": ("LLM_API_KEY", ""),
    "llm_primary_model": ("LLM_PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL),
    "llm_review_model": ("LLM_REVIEW_MODEL", DEFAULT_REVIEW_MODEL),
    "llm_evidence_model": ("LLM_EVIDENCE_MODEL", DEFAULT_EVIDENCE_MODEL),
    "llm_reasoning_effort": ("LLM_REASONING_EFFORT", ""),
    "embedding_mode": ("EMBEDDING_MODE", "api"),
    "embedding_model": ("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    "feishu_app_id": ("FEISHU_APP_ID", ""),
    "feishu_app_secret": ("FEISHU_APP_SECRET", ""),
    "feishu_bitable_app_token": ("FEISHU_BITABLE_APP_TOKEN", ""),
    "feishu_feedback_table_id": ("FEISHU_FEEDBACK_TABLE_ID", ""),
    "feishu_evidence_table_id": ("FEISHU_EVIDENCE_TABLE_ID", ""),
    "feishu_review_table_id": ("FEISHU_REVIEW_TABLE_ID", ""),
    "feishu_experiment_table_id": ("FEISHU_EXPERIMENT_TABLE_ID", ""),
}

_INT_ENV_KEYS = {
    "llm_timeout_seconds": "LLM_TIMEOUT_SECONDS",
    "llm_max_retries": "LLM_MAX_RETRIES",
    "embedding_dimension": "EMBEDDING_DIMENSION",
}


@dataclass
class Config:
    """RidePulse 全局配置。

    所有字段均可通过环境变量覆盖，生产凭证绝不硬编码。
    """

    # -- 运行模式 --
    env: str = os.getenv("RIDEPULSE_ENV", "development")
    db_path: Path = Path(os.getenv("RIDEPULSE_DB_PATH", "data/ridepulse.db"))
    output_dir: Path = Path(os.getenv("RIDEPULSE_OUTPUT_DIR", "output"))

    # -- LLM（默认 OpenAI GPT-6 系列） --
    llm_base_url: str = os.getenv("LLM_BASE_URL", DEFAULT_OPENAI_BASE_URL)
    llm_api_key: str = os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    llm_primary_model: str = os.getenv("LLM_PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL)
    llm_review_model: str = os.getenv("LLM_REVIEW_MODEL", DEFAULT_REVIEW_MODEL)
    llm_evidence_model: str = os.getenv("LLM_EVIDENCE_MODEL", DEFAULT_EVIDENCE_MODEL)
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # -- Embedding --
    embedding_mode: str = os.getenv("EMBEDDING_MODE", "api")  # api / local / fake
    embedding_model: str = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    embedding_dimension: int = int(
        os.getenv("EMBEDDING_DIMENSION", str(DEFAULT_EMBEDDING_DIMENSION)) or "0"
    )

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
    def llm_provider(self) -> str:
        """供应商标识：官方端点记 openai，其余记 openai-compatible。"""
        return "openai" if "api.openai.com" in (self.llm_base_url or "") else "openai-compatible"

    @property
    def llm_model_stack(self) -> dict[str, str]:
        """三层模型分工（写进运行报告，便于回溯每次结果由哪个模型产出）。"""
        return {
            "classify": self.llm_primary_model,
            "review": self.llm_review_model or self.llm_primary_model,
            "evidence": self.llm_evidence_model or self.llm_primary_model,
        }

    def reasoning_effort_for(self, stage: str) -> str:
        """取某阶段的推理强度：全局设置优先，否则按阶段默认。"""
        return self.llm_reasoning_effort or DEFAULT_REASONING_EFFORT.get(stage, "low")

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
        # 字段值仍是类默认值时，从环境变量回读（覆盖 .env 加载晚于 import 的问题）；
        # 显式传入的非默认值优先，不被覆盖。
        for attr, (env_key, default) in _STR_ENV_KEYS.items():
            value = os.getenv(env_key)
            if value is not None and getattr(self, attr) == default:
                setattr(self, attr, value)
        for attr, env_key in _INT_ENV_KEYS.items():
            value = os.getenv(env_key)
            if value is not None:
                setattr(self, attr, int(value))
        # 兼容 OpenAI 官方命名的凭证变量（GitHub Actions 里通常只配 OPENAI_API_KEY）
        if not self.llm_api_key:
            self.llm_api_key = os.getenv("OPENAI_API_KEY", "")
        if not self.llm_base_url:
            self.llm_base_url = os.getenv("OPENAI_BASE_URL", "") or DEFAULT_OPENAI_BASE_URL
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
