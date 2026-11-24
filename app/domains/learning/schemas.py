from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

LearningScope = Literal["personal", "team", "organization"]
ArtifactStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "shadow",
    "canary",
    "active",
    "rolled_back",
    "superseded",
    "archived",
]


class PreferenceUpsert(BaseModel):
    employee_id: int
    key: str = Field(min_length=1, max_length=128, description="如 address_style / output_format")
    value: str = Field(min_length=1, max_length=4000)
    scope: LearningScope = "personal"
    source: Literal["manual", "real_time", "feedback"] = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: datetime | None = None


class PreferenceUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=4000)
    scope: LearningScope | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["active", "archived"] | None = None
    expires_at: datetime | None = None


class PreferenceOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    key: str
    value: str
    scope: str
    source: str
    confidence: float
    status: str
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InterventionCreate(BaseModel):
    employee_id: int | None = None
    instance_id: int | None = None
    step_id: int | None = None
    trace_id: str | None = Field(default=None, max_length=64)
    source_type: str = Field(default="single_demonstration", max_length=64)
    original_output: dict = Field(default_factory=dict)
    final_output: dict = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=4000)


class InterventionStatusUpdate(BaseModel):
    status: Literal["new", "attributed", "artifact_created", "archived"]


class InterventionOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    instance_id: int | None = None
    step_id: int | None = None
    trace_id: str | None = None
    actor_id: int | None = None
    source_type: str
    original_output: dict
    final_output: dict
    diff: list
    comment: str | None = None
    status: str
    created_at: datetime


class ArtifactCreate(BaseModel):
    employee_id: int | None = None
    source: dict = Field(default_factory=dict)
    attribution: str = Field(default="", max_length=128)
    target_layer: Literal[
        "semantic_memory",
        "procedural_memory",
        "persona_layer",
        "tool_config",
        "skill_gap",
    ] = "procedural_memory"
    proposal: dict = Field(default_factory=dict)
    evidence: list = Field(default_factory=list)
    eval_result: dict = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "medium"
    scope: LearningScope = "personal"
    rollout: dict = Field(default_factory=dict)
    expires_at: datetime | None = None
    supersedes_id: int | None = None
    status: ArtifactStatus = "pending_approval"


class ArtifactDecision(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ArtifactVersionCreate(BaseModel):
    attribution: str | None = Field(default=None, max_length=128)
    target_layer: Literal[
        "semantic_memory",
        "procedural_memory",
        "persona_layer",
        "tool_config",
        "skill_gap",
    ] | None = None
    proposal: dict | None = None
    evidence: list | None = None
    risk: Literal["low", "medium", "high"] | None = None
    scope: LearningScope | None = None
    rollout: dict | None = None


class ArtifactOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    source: dict
    attribution: str
    target_layer: str
    proposal: dict
    evidence: list
    eval_result: dict
    risk: str
    scope: str
    status: str
    rollout: dict
    version: int
    supersedes_id: int | None = None
    rollback_of: int | None = None
    expires_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


AttributionCategory = Literal[
    "knowledge_missing",
    "retrieval_miss",
    "tool_misuse",
    "planning_error",
    "style_mismatch",
    "permission_violation",
    "intent_misunderstanding",
    "unknown",
]


class AttributionAnalyzeRequest(BaseModel):
    instance_id: int | None = None
    intervention_id: int | None = None
    employee_id: int | None = None
    persist: bool = True
    use_llm: bool = False


class AttributionStatusUpdate(BaseModel):
    status: Literal["new", "routed", "artifact_created", "resolved"]


class AttributionOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    instance_id: int | None = None
    step_id: int | None = None
    intervention_id: int | None = None
    trace_id: str | None = None
    category: str
    confidence: float
    signals: list
    suggestion: str
    routed_action: str
    artifact_id: int | None = None
    source: str
    status: str
    created_at: datetime


class EvaluationSuiteCreate(BaseModel):
    employee_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = Field(default=None, max_length=512)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    regression_tolerance: float = Field(default=0.02, ge=0.0, le=1.0)
    enforce_on_activate: bool = True
    enabled: bool = True


class EvaluationSuiteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    regression_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    enforce_on_activate: bool | None = None
    enabled: bool | None = None


class EvaluationSuiteOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    name: str
    code: str
    description: str | None = None
    threshold: float
    regression_tolerance: float
    enforce_on_activate: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EvaluationCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    case_type: Literal["llm", "assertion"] = "llm"
    input: dict = Field(default_factory=dict)
    expected: dict = Field(default_factory=dict)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    enabled: bool = True


class EvaluationCaseUpdate(BaseModel):
    name: str | None = None
    case_type: Literal["llm", "assertion"] | None = None
    input: dict | None = None
    expected: dict | None = None
    weight: float | None = Field(default=None, gt=0.0, le=10.0)
    enabled: bool | None = None


class EvaluationCaseOut(ORMModel):
    id: int
    suite_id: int
    name: str
    case_type: str
    input: dict
    expected: dict
    weight: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EvaluationRunRequest(BaseModel):
    outputs: dict[str, str] = Field(
        default_factory=dict,
        description="assertion 用例的输出覆盖，键为 case_id",
    )


class EvaluationRunOut(ORMModel):
    id: int
    tenant_id: int
    suite_id: int
    employee_id: int | None = None
    artifact_id: int | None = None
    trigger: str
    status: str
    score: float
    baseline_score: float | None = None
    delta: float | None = None
    passed: bool
    threshold: float
    details: list
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TrialCreate(BaseModel):
    mode: Literal["shadow", "certification"] = "shadow"
    sample_size: int = Field(default=20, ge=1, le=200)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)


class ArtifactRolloutRequest(BaseModel):
    mode: Literal["shadow", "canary", "full"] = "shadow"
    traffic: float = Field(default=0.1, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=1000)


class ArtifactShareRequest(BaseModel):
    scope: Literal["team", "organization"] = "team"
    note: str | None = Field(default=None, max_length=1000)


class LearningQuestionCreate(BaseModel):
    employee_id: int
    instance_id: int | None = None
    question: str = Field(min_length=1, max_length=2000)
    options: list[dict] = Field(default_factory=list)
    default_option: str | None = Field(default=None, max_length=128)
    expires_at: datetime | None = None


class LearningQuestionAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=512)
    note: str | None = Field(default=None, max_length=2000)


class LearningQuestionOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    instance_id: int | None = None
    question: str
    options: list
    default_option: str | None = None
    status: str
    answer: str | None = None
    answer_note: str | None = None
    answered_by: int | None = None
    answered_at: datetime | None = None
    expires_at: datetime | None = None
    artifact_id: int | None = None
    created_at: datetime
    updated_at: datetime


class WeeklyReviewGenerate(BaseModel):
    employee_id: int | None = None
    week_start: datetime | None = None


class WeeklyReviewBatchGenerate(BaseModel):
    week_start: datetime | None = None
    force: bool = False
    deliver: bool = False


class WeeklyReviewOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    period_start: datetime
    period_end: datetime
    metrics: dict
    top_errors: list
    learned: dict
    recommendations: list
    summary: str
    status: str
    created_at: datetime


class ExpertTrajectoryDistillRequest(BaseModel):
    instance_id: int
    name: str | None = Field(default=None, max_length=128)
    scope: LearningScope = "personal"


class PreferenceCollectRequest(BaseModel):
    employee_id: int | None = None
    sources: list[Literal["intervention", "evaluation", "feedback"]] = Field(
        default_factory=lambda: ["intervention", "evaluation", "feedback"]
    )
    limit: int = Field(default=200, ge=1, le=5000)


class PreferencePairOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    source_type: str
    source_ref: str
    prompt: str
    chosen: str
    rejected: str
    chosen_score: float | None = None
    rejected_score: float | None = None
    pair_metadata: dict
    status: str
    created_at: datetime


class PreferenceCollectResult(BaseModel):
    created: int
    skipped: int
    pairs: list[PreferencePairOut] = Field(default_factory=list)


class PreferenceExportRequest(BaseModel):
    employee_id: int | None = None
    pair_ids: list[int] = Field(default_factory=list)
    format: Literal["dpo_jsonl"] = "dpo_jsonl"


class PreferenceExportResult(BaseModel):
    path: str
    count: int
    bytes: int


class TrainingJobCreate(BaseModel):
    employee_id: int | None = None
    method: Literal["dpo", "sft"] = "dpo"
    dataset_path: str = Field(min_length=1, max_length=512)
    config: dict = Field(default_factory=dict)


class TrainingJobStatusUpdate(BaseModel):
    status: Literal["running", "succeeded", "failed", "cancelled"]
    metrics: dict = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)


class FewShotCreate(BaseModel):
    name: str = Field(default="", max_length=128)
    input: str = Field(min_length=1, max_length=8000)
    output: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    source: Literal["manual", "onboarding", "expert"] = "manual"


class FewShotUpdate(BaseModel):
    name: str | None = None
    input: str | None = None
    output: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class FewShotOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    name: str
    input: str
    output: str
    tags: list
    enabled: bool
    source: str
    created_at: datetime


class FewShotBulkCreate(BaseModel):
    examples: list[FewShotCreate] = Field(min_length=1, max_length=200)


class OutcomeCreate(BaseModel):
    employee_id: int | None = None
    instance_id: int | None = None
    artifact_id: int | None = None
    outcome_type: str = Field(default="custom", min_length=1, max_length=64)
    success: bool = True
    value: float | None = None
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime | None = None


class OutcomeOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    instance_id: int | None = None
    artifact_id: int | None = None
    outcome_type: str
    success: bool
    value: float | None = None
    payload: dict
    occurred_at: datetime
    created_at: datetime


class MemoryCompressRequest(BaseModel):
    before_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=100, ge=1, le=500)


class OnboardingImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    source_type: Literal["jd", "sop", "policy"] = "jd"
    apply_contract: bool = True
    knowledge_base_id: int | None = None
    title: str | None = Field(default=None, max_length=255)


class OnboardingExtractResult(BaseModel):
    role: str = ""
    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    must_ask: list[str] = Field(default_factory=list)
    kpi: dict = Field(default_factory=dict)
    source: str = "heuristic"
    contract_id: int | None = None
    knowledge_document_id: int | None = None


class TrainingJobOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    method: str
    dataset_path: str
    dataset_size: int
    status: str
    config: dict
    metrics: dict
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TrialOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int
    mode: str
    status: str
    sample_size: int
    threshold: float
    metrics: dict
    details: list
    decision: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ImplicitSignalCreate(BaseModel):
    employee_id: int | None = None
    instance_id: int | None = None
    trace_id: str | None = Field(default=None, max_length=64)
    signal_type: Literal[
        "repeat_question", "rephrase", "abandon", "copy_segment", "custom"
    ] = "repeat_question"
    content: str = Field(default="", max_length=10000)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    payload: dict = Field(default_factory=dict)


class ImplicitSignalOut(ORMModel):
    id: int
    tenant_id: int
    employee_id: int | None = None
    instance_id: int | None = None
    trace_id: str | None = None
    signal_type: str
    content: str
    weight: float
    payload: dict
    created_at: datetime
