"""RidePulse AI 统一数据模型 — Pydantic v2.

本模块定义全系统所有数据结构的唯一来源。
任何模块不得另建一套字段命名。

字段定义依据:
  - 15_40强完整方案与系统落地执行手册.md §5
  - 16_三人并行任务执行文档_最终简化版.md §5
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# ============================================================
# 枚举类型
# ============================================================

class SourceType(str, Enum):
    """来源渠道类型。"""
    APP_STORE = "app_store"
    ECOMMERCE = "ecommerce"
    FORUM = "forum"
    SOCIAL = "social"
    SUPPORT = "support"
    NEWS = "news"
    OTHER = "other"


class PermalinkLevel(str, Enum):
    """来源链接精度。"""
    EXACT_RECORD = "exact_record"      # 可精确定位到单条评论/帖子
    PAGE_ONLY = "page_only"            # 只能到页面级（如App Store首页）
    ARCHIVE_ONLY = "archive_only"      # 仅存档
    UNVERIFIED = "unverified"          # 未核验


class DatePrecision(str, Enum):
    """日期精度。"""
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class TextProvenance(str, Enum):
    """原文逐字程度——仅描述 original_text 是否为逐字原文。"""
    VERBATIM = "verbatim"
    PARAPHRASED = "paraphrased"
    UNVERIFIED = "unverified"


class TranslationMethod(str, Enum):
    """翻译方法。"""
    NOT_NEEDED = "not_needed"
    HUMAN = "human"
    AI = "ai"
    UNVERIFIED = "unverified"


class EvidenceStatus(str, Enum):
    """证据核验状态。"""
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


class Sentiment(int, Enum):
    """情感: 1=强烈负面 2=负面 3=中性 4=正面 5=强烈正面。"""
    STRONG_NEGATIVE = 1
    NEGATIVE = 2
    NEUTRAL = 3
    POSITIVE = 4
    STRONG_POSITIVE = 5


class ThemePrimary(str, Enum):
    """一级主题分类。"""
    CONNECTIVITY = "connectivity"
    FIRMWARE = "firmware"
    NAVIGATION = "navigation"
    DATA_ACCURACY = "data_accuracy"
    HARDWARE = "hardware"
    DISPLAY_UX = "display_ux"
    AFTER_SALES = "after_sales"
    PRICE_VALUE = "price_value"
    COMPATIBILITY = "compatibility"
    FEATURE_REQUEST = "feature_request"
    PACKAGING = "packaging"
    OTHER = "other"


class NeedType(str, Enum):
    """需求五分类 — 区别于情感分析的核心设计。

    同一"同步失败"表述，五分类可区分是功能缺失、用户操作误解、还是偶发网络超时。
    """
    REAL_NEED = "real_need"
    FEATURE_REQUEST = "feature_request"
    OPERATION_MISUNDERSTANDING = "operation_misunderstanding"
    INCIDENTAL_FAILURE = "incidental_failure"
    EMOTIONAL_COMPLAINT = "emotional_complaint"
    UNKNOWN = "unknown"


class Scenario(str, Enum):
    """使用场景。"""
    TRAINING = "training"
    COMMUTING = "commuting"
    RACING = "racing"
    LEISURE = "leisure"
    INDOOR = "indoor"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class UserType(str, Enum):
    """用户类型。"""
    BEGINNER = "beginner"
    ENTHUSIAST = "enthusiast"
    COMPETITIVE = "competitive"
    CASUAL = "casual"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """严重度: S1=安全关键 S2=核心功能不可用 S3=功能严重受损 S4=体验下降 S5=轻度不便。"""
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"


class PurchaseImpact(str, Enum):
    """购买影响。"""
    BLOCKER = "blocker"
    INFLUENCE = "influence"
    NO_IMPACT = "no_impact"
    UNKNOWN = "unknown"


class ReviewConflictStatus(str, Enum):
    """第一轮vs第二轮对比状态。"""
    AGREED = "agreed"
    CONFLICT = "conflict"
    FAILED = "failed"


class HumanReviewStatus(str, Enum):
    """人工复核状态。"""
    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class PipelineState(str, Enum):
    """Pipeline运行状态。"""
    CREATED = "CREATED"
    COLLECTED_OR_IMPORTED = "COLLECTED_OR_IMPORTED"
    VALIDATED = "VALIDATED"
    DEDUPED = "DEDUPED"
    CLASSIFIED = "CLASSIFIED"
    REVIEWED = "REVIEWED"
    WAITING_HUMAN_REVIEW = "WAITING_HUMAN_REVIEW"
    CLUSTERED = "CLUSTERED"
    SCORED = "SCORED"
    CARDS_GENERATED = "CARDS_GENERATED"
    WAITING_CARD_APPROVAL = "WAITING_CARD_APPROVAL"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PriorityLevel(str, Enum):
    """优先级等级。"""
    P0 = "P0"  # >= 80
    P1 = "P1"  # 65-79
    P2 = "P2"  # 45-64
    P3 = "P3"  # < 45


class ConfidenceLevel(str, Enum):
    """置信度等级。"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================
# 辅助类型
# ============================================================

# ISO 639-1 语言代码
LanguageCode = Annotated[str, StringConstraints(min_length=2, max_length=3, pattern=r"^[a-z]{2,3}$")]

# ID格式
FeedbackID = Annotated[str, StringConstraints(pattern=r"^F\d{4}$")]
ClusterID = Annotated[str, StringConstraints(pattern=r"^CL-\d{4}$")]
CardID = Annotated[str, StringConstraints(pattern=r"^EC-\d{4}-\d{4}$")]
RunID = Annotated[str, StringConstraints(pattern=r"^RUN-\d{8}-\d{6}$")]

# URL (HTTPS only)
HttpsUrl = Annotated[str, StringConstraints(min_length=1)]


# ============================================================
# 核心数据模型
# ============================================================

class FeedbackRecord(BaseModel):
    """单条用户反馈的结构化记录——全系统统一数据契约。

    对应文档15 §5.1 和文档16 §5.1。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # -- 标识 --
    feedback_id: str = Field(..., description="唯一反馈标识符，如 F0001")
    source_record_id: str = Field(..., description="同一原帖内多条反馈共享此ID")
    ingest_batch_id: str = Field(..., description="导入批次标识")

    # -- 来源 --
    source_platform: str = Field(..., description="来源平台名称")
    source_type: SourceType = Field(..., description="来源渠道类型")
    source_url: str = Field(..., description="最接近原始内容的URL")
    source_permalink_level: PermalinkLevel = Field(..., description="链接精度")
    source_date: date | None = Field(default=None, description="原始日期")
    source_date_raw: str | None = Field(default=None, description="页面原始日期文本")
    source_date_precision: DatePrecision = Field(..., description="日期精度")
    accessed_at: date = Field(..., description="核验/访问日期")

    # -- 语言与市场 --
    language: str = Field(..., description="ISO 639-1语言代码，如 zh/en/de/ja")
    market: str = Field(default="unknown", description="国家或地区，未知填 unknown")

    # -- 产品 --
    brand: str = Field(..., description="产品品牌")
    product_model: str | None = Field(default=None, description="产品型号，未出现填 null")
    firmware_version: str | None = Field(default=None, description="固件版本，未出现填 null")
    app_version: str | None = Field(default=None, description="App版本，未出现填 null")

    # -- 文本 --
    original_text: str = Field(..., min_length=1, description="逐字原文，不修改")
    translated_text: str | None = Field(default=None, description="中文译文，不覆盖原文")
    text_provenance: TextProvenance = Field(..., description="original_text 是否为逐字原文")
    translation_method: TranslationMethod = Field(..., description="翻译方式")

    # -- 存档 --
    archive_path: str | None = Field(default=None, description="本地截图/存档相对路径")
    archive_sha256: str | None = Field(default=None, description="存档文件 SHA-256")

    # -- 核验 --
    evidence_status: EvidenceStatus = Field(..., description="证据核验状态")
    verification_note: str | None = Field(default=None, description="核验说明与边界")

    @field_validator("source_url")
    @classmethod
    def url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError(f"source_url 必须是 HTTPS: {v}")
        return v

    @field_validator("language")
    @classmethod
    def language_must_be_iso(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z]{2,3}", v):
            raise ValueError(f"language 必须是 ISO 639-1 代码: {v}")
        return v

    @field_validator("feedback_id")
    @classmethod
    def feedback_id_format(cls, v: str) -> str:
        if not re.fullmatch(r"F\d{4}", v):
            raise ValueError(f"feedback_id 格式必须为 F0001: {v}")
        return v


class ClassificationResult(BaseModel):
    """第一轮AI分类结果。

    对应文档15 §5.2 和文档16 §5.2。
    """

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(..., description="关联的反馈ID")
    sentiment: Sentiment = Field(..., description="情感")
    theme_primary: ThemePrimary = Field(..., description="一级主题")
    theme_secondary: list[ThemePrimary] = Field(default_factory=list, description="二级主题")
    need_type: NeedType = Field(..., description="需求五分类")
    scenario: Scenario = Field(default=Scenario.UNKNOWN, description="使用场景")
    user_type: UserType = Field(default=UserType.UNKNOWN, description="用户类型")
    severity: Severity = Field(..., description="严重度")
    purchase_impact: PurchaseImpact = Field(default=PurchaseImpact.UNKNOWN, description="购买影响")
    jtbd: str = Field(..., min_length=10, description="待完成任务: 用户希望[动作]以达成[目标]")
    root_cause_hypotheses: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="根因假设，最多3条，每条标记为待验证",
    )
    is_actionable: bool = Field(..., description="是否包含可行动信息")
    is_constructive: bool = Field(..., description="是否包含建设性建议")
    confidence: float = Field(..., ge=0.0, le=1.0, description="分类置信度")
    rationale: str = Field(..., max_length=200, description="分类理由")
    model_name: str = Field(..., description="使用的模型名")
    prompt_version: str = Field(..., description="Prompt版本")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class ReviewResult(BaseModel):
    """独立第二轮复判结果。

    对应文档15 §5.3 和文档16 §5.3。
    """

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(..., description="关联的反馈ID")
    review_sentiment: Sentiment = Field(..., description="复判情感")
    review_theme_primary: ThemePrimary = Field(..., description="复判一级主题")
    review_need_type: NeedType = Field(..., description="复判需求五分类")
    review_severity: Severity = Field(..., description="复判严重度")
    review_purchase_impact: PurchaseImpact = Field(..., description="复判购买影响")
    review_jtbd: str = Field(..., description="复判JTBD")
    review_confidence: float = Field(..., ge=0.0, le=1.0, description="复判置信度")
    conflict_fields: list[str] = Field(default_factory=list, description="冲突字段名列表")
    review_status: ReviewConflictStatus = Field(..., description="agreed/conflict/failed")
    human_review_required: bool = Field(..., description="是否需要人工复核")
    model_name: str = Field(..., description="复判模型名")
    prompt_version: str = Field(..., description="Prompt版本")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class HumanReview(BaseModel):
    """人工复核记录。"""

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(..., description="关联的反馈ID")
    primary_result: ClassificationResult | None = Field(default=None, description="第一轮结果")
    review_result: ReviewResult | None = Field(default=None, description="第二轮结果")
    conflict_fields: list[str] = Field(default_factory=list, description="冲突字段")
    final_sentiment: Sentiment | None = Field(default=None, description="最终情感")
    final_theme_primary: ThemePrimary | None = Field(default=None, description="最终一级主题")
    final_need_type: NeedType | None = Field(default=None, description="最终五分类")
    final_severity: Severity | None = Field(default=None, description="最终严重度")
    final_purchase_impact: PurchaseImpact | None = Field(default=None, description="最终购买影响")
    review_status: HumanReviewStatus = Field(default=HumanReviewStatus.PENDING, description="复核状态")
    review_note: str | None = Field(default=None, description="复核理由")
    reviewer: str | None = Field(default=None, description="复核人标识")
    reviewed_at: datetime | None = Field(default=None, description="复核时间")
    created_at: datetime = Field(default_factory=datetime.now, description="记录创建时间")


class EvidenceCard(BaseModel):
    """需求证据卡。

    对应文档15 §5.4 和文档16 §5.4。
    """

    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(..., description="证据卡ID，如 EC-2026-0001")
    cluster_id: str = Field(..., description="关联需求簇ID")

    @field_validator("card_id")
    @classmethod
    def card_id_format(cls, v: str) -> str:
        if not re.fullmatch(r"EC-\d{4}-\d{4}", v):
            raise ValueError(f"card_id 格式必须为 EC-2026-0001: {v}")
        return v

    @field_validator("cluster_id")
    @classmethod
    def cluster_id_format(cls, v: str) -> str:
        if not re.fullmatch(r"CL-\d{4}", v):
            raise ValueError(f"cluster_id 格式必须为 CL-0001: {v}")
        return v
    title: str = Field(..., min_length=1, description="具体问题标题，不得写空泛'建议优化'")
    problem_statement: str = Field(..., description="只描述证据支持的问题")
    priority_score: int = Field(..., ge=0, le=100, description="优先级分数 0-100，由代码计算")
    priority_level: PriorityLevel = Field(..., description="优先级等级")
    confidence_level: ConfidenceLevel = Field(..., description="置信度等级")
    evidence_ids: list[str] = Field(..., min_length=1, description="引用反馈ID数组")
    platforms: list[str] = Field(default_factory=list, description="涉及平台")
    brands: list[str] = Field(default_factory=list, description="涉及品牌")
    languages: list[str] = Field(default_factory=list, description="涉及语言")
    root_cause_hypotheses: list[str] = Field(default_factory=list, description="待验证根因假设")
    counter_evidence: str | None = Field(default=None, description="反证和替代解释")
    recommended_actions: list[dict[str, str]] = Field(default_factory=list, description="可执行动作")
    suggested_owner: str | None = Field(default=None, description="建议责任团队")
    human_review_status: HumanReviewStatus = Field(
        default=HumanReviewStatus.PENDING,
        description="人工复核状态",
    )
    model_name: str | None = Field(default=None, description="生成模型")
    prompt_version: str | None = Field(default=None, description="Prompt版本")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class ClusterInfo(BaseModel):
    """需求簇信息（由聚类算法输出）。"""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(..., description="簇ID，如 CL-0001")
    member_feedback_ids: list[str] = Field(..., min_length=1, description="成员反馈ID列表")
    unique_source_record_count: int = Field(..., ge=0, description="去重后独立用户数")
    unique_domain_count: int = Field(..., ge=0, description="独立域名数")
    platform_count: int = Field(..., ge=0, description="平台数")
    language_count: int = Field(..., ge=0, description="语言数")
    brand_count: int = Field(..., ge=0, description="品牌数")
    max_severity: Severity = Field(..., description="最高严重度")
    time_range_days: int | None = Field(default=None, description="时间跨度（天）")
    is_noise: bool = Field(default=False, description="是否为噪声点")
    theme_primary: ThemePrimary | None = Field(default=None, description="对应一级主题")


class RunSummary(BaseModel):
    """一次Pipeline运行的摘要。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="运行批次ID: RUN-YYYYMMDD-HHMMSS")
    state: PipelineState = Field(default=PipelineState.CREATED, description="当前状态")
    total_input: int = Field(default=0, description="输入总数")
    valid_count: int = Field(default=0, description="有效数")
    deduped_count: int = Field(default=0, description="去重后数")
    classified_count: int = Field(default=0, description="已分类数")
    conflict_count: int = Field(default=0, description="分类冲突数")
    human_review_count: int = Field(default=0, description="待人工复核数")
    cluster_count: int = Field(default=0, description="需求簇数")
    card_count: int = Field(default=0, description="证据卡数")
    delivered_count: int = Field(default=0, description="已推送飞书数")
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None)


class ValidationReport(BaseModel):
    """CSV导入校验报告。"""

    model_config = ConfigDict(extra="forbid")

    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_ids: list[str] = Field(default_factory=list)
    missing_fields: dict[str, int] = Field(default_factory=dict)
    invalid_urls: list[str] = Field(default_factory=list)
    unverified_evidence_count: int = 0
    warnings: list[str] = Field(default_factory=list)


# ============================================================
# 严重度→分数映射（用于确定性评分）
# ============================================================

SEVERITY_SCORE: dict[Severity, int] = {
    Severity.S1: 20,
    Severity.S2: 16,
    Severity.S3: 11,
    Severity.S4: 6,
    Severity.S5: 2,
}

PURCHASE_IMPACT_SCORE: dict[PurchaseImpact, int] = {
    PurchaseImpact.BLOCKER: 15,
    PurchaseImpact.INFLUENCE: 8,
    PurchaseImpact.NO_IMPACT: 0,
    PurchaseImpact.UNKNOWN: 0,
}
