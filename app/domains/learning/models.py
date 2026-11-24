from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class FeedbackSample(IdMixin, TenantMixin, TimestampMixin, Base):
    """人工反馈与 bad case 样本，用于后续评测与迭代。"""

    __tablename__ = "feedback_samples"

    instance_id: Mapped[int | None] = mapped_column(
        Integer, index=True, comment="关联 task_instances.id"
    )
    employee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="1-5 分")
    verdict: Mapped[str] = mapped_column(
        String(32),
        default="unknown",
        nullable=False,
        comment="accepted/rejected/corrected/unknown",
    )
    comment: Mapped[str | None] = mapped_column(Text)
    corrected_output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="new", nullable=False, comment="new/labeled/archived"
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class InterventionDelta(IdMixin, TenantMixin, TimestampMixin, Base):
    """人工接管增量（HITL Intervention Delta）。

    记录 Agent 原输出与人工终稿的结构化差异，是学习流水线价值最高的信号源。
    """

    __tablename__ = "intervention_deltas"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    step_id: Mapped[int | None] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(
        String(64), default="human_takeover_diff", nullable=False
    )
    original_output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    final_output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    diff: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        default="new",
        index=True,
        nullable=False,
        comment="new/attributed/artifact_created/archived",
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class PreferenceMemory(IdMixin, TenantMixin, TimestampMixin, Base):
    """偏好记忆：称呼、格式、结论先行等实时生效的人格层记忆。"""

    __tablename__ = "preference_memories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "key", name="uq_preferences_employee_key"),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scope: Mapped[str] = mapped_column(
        String(32), default="personal", nullable=False, comment="personal/team/organization"
    )
    source: Mapped[str] = mapped_column(
        String(64), default="manual", nullable=False, comment="manual/real_time/feedback"
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, comment="active/archived"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class LearningArtifact(IdMixin, TenantMixin, TimestampMixin, Base):
    """学习工件：可溯源、可审批、可回滚的学习候选。"""

    __tablename__ = "learning_artifacts"
    __table_args__ = (
        Index("ix_learning_artifacts_status_scope", "status", "scope"),
    )

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    source: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attribution: Mapped[str] = mapped_column(
        String(128), default="", nullable=False, comment="失败归因分类"
    )
    target_layer: Mapped[str] = mapped_column(
        String(64),
        default="procedural_memory",
        nullable=False,
        comment="semantic_memory/procedural_memory/persona_layer/tool_config",
    )
    proposal: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    eval_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    scope: Mapped[str] = mapped_column(
        String(32), default="personal", nullable=False, comment="personal/team/organization"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_approval",
        nullable=False,
        comment=(
            "draft/pending_approval/approved/rejected/shadow/canary/active/"
            "rolled_back/superseded/archived"
        ),
    )
    rollout: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)
    rollback_of: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class FailureAttribution(IdMixin, TenantMixin, TimestampMixin, Base):
    """失败归因：把一次失败强制归入一类，并路由到对应修复动作。"""

    __tablename__ = "failure_attributions"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    step_id: Mapped[int | None] = mapped_column(Integer, index=True)
    intervention_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("intervention_deltas.id"), index=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(
        String(64),
        default="unknown",
        nullable=False,
        index=True,
        comment=(
            "knowledge_missing/retrieval_miss/tool_misuse/planning_error/"
            "style_mismatch/permission_violation/intent_misunderstanding/unknown"
        ),
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    suggestion: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    routed_action: Mapped[str] = mapped_column(
        String(64),
        default="",
        nullable=False,
        comment="create_knowledge_ticket/retune_chunk/fix_tool_schema/add_sop_step/"
        "update_persona/tighten_permission/collect_intent_samples",
    )
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learning_artifacts.id"), index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), default="rule", nullable=False, comment="rule/llm/manual"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="new",
        index=True,
        nullable=False,
        comment="new/routed/artifact_created/resolved",
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class EvaluationSuite(IdMixin, TenantMixin, TimestampMixin, Base):
    """综合评估套件：一组岗位测试用例，用于回归与上岗验收。"""

    __tablename__ = "evaluation_suites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_evaluation_suites_tenant_code"),
    )

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    regression_tolerance: Mapped[float] = mapped_column(Float, default=0.02, nullable=False)
    enforce_on_activate: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class EvaluationCase(IdMixin, TimestampMixin, Base):
    """评估用例：llm 类型由大模型作答后打分，assertion 类型直接对比给定输出。"""

    __tablename__ = "evaluation_cases"

    suite_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evaluation_suites.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    case_type: Mapped[str] = mapped_column(
        String(32), default="llm", nullable=False, comment="llm/assertion"
    )
    input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expected: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EvaluationRun(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次综合评估执行结果。"""

    __tablename__ = "evaluation_runs"

    suite_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evaluation_suites.id"), nullable=False, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learning_artifacts.id"), index=True
    )
    trigger: Mapped[str] = mapped_column(
        String(64), default="manual", nullable=False, comment="manual/artifact_activation"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="running",
        index=True,
        nullable=False,
        comment="running/succeeded/failed",
    )
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    baseline_score: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    details: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class LearningQuestion(IdMixin, TenantMixin, TimestampMixin, Base):
    """主动学习提问：把“我不确定”变成资产，受每日预算约束。"""

    __tablename__ = "learning_questions"
    __table_args__ = (
        Index("ix_learning_questions_status_expires", "status", "expires_at"),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    default_option: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16),
        default="open",
        nullable=False,
        comment="open/answered/dismissed/expired",
    )
    answer: Mapped[str | None] = mapped_column(String(512))
    answer_note: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[int | None] = mapped_column(Integer)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learning_artifacts.id")
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class FewShotExample(IdMixin, TenantMixin, TimestampMixin, Base):
    """入职案例 / 示范库：用于规划与 LLM 步骤的 Few-shot 上下文。"""

    __tablename__ = "few_shot_examples"

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    input: Mapped[str] = mapped_column(Text, default="", nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), default="manual", nullable=False, comment="manual/onboarding/expert"
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class OutcomeEvent(IdMixin, TenantMixin, TimestampMixin, Base):
    """业务结果回执（Outcome Telemetry），是唯一客观的 ground truth 信号。"""

    __tablename__ = "outcome_events"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learning_artifacts.id"), index=True
    )
    outcome_type: Mapped[str] = mapped_column(
        String(64), default="custom", nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class PreferencePair(IdMixin, TenantMixin, TimestampMixin, Base):
    """DPO/RLHF 偏好对：来自接管增量、评估结果或人工修正。"""

    __tablename__ = "preference_pairs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_ref", name="uq_preference_pairs_source"),
    )

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(32), default="intervention", nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chosen: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rejected: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chosen_score: Mapped[float | None] = mapped_column(Float)
    rejected_score: Mapped[float | None] = mapped_column(Float)
    pair_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="draft",
        index=True,
        nullable=False,
        comment="draft/exported/archived",
    )
    created_by: Mapped[int | None] = mapped_column(Integer)


class TrainingJob(IdMixin, TenantMixin, TimestampMixin, Base):
    """训练任务台账；平台负责数据集导出与状态回调，训练由外部 trainer 执行。"""

    __tablename__ = "training_jobs"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    method: Mapped[str] = mapped_column(
        String(16), default="dpo", nullable=False, comment="dpo/sft"
    )
    dataset_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    dataset_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        index=True,
        nullable=False,
        comment="pending/dispatched/running/succeeded/failed/cancelled",
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class WeeklyReview(IdMixin, TenantMixin, TimestampMixin, Base):
    """成长周报：给管理员与老板看的数字员工成长复盘。"""

    __tablename__ = "weekly_reviews"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    top_errors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    learned: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    recommendations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="generated", nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)


class EmployeeTrial(IdMixin, TenantMixin, TimestampMixin, Base):
    """影子试运行 / 上岗资格认证记录。"""

    __tablename__ = "employee_trials"

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(
        String(32), default="shadow", nullable=False, comment="shadow/certification"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="running",
        nullable=False,
        comment="running/passed/failed/cancelled",
    )
    sample_size: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    details: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    decision: Mapped[str | None] = mapped_column(
        String(32), comment="go_live/downgrade/rejected"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)


class ImplicitSignal(IdMixin, TenantMixin, TimestampMixin, Base):
    """隐式学习信号：重复追问、换说法、中途放弃、复制片段等。"""

    __tablename__ = "implicit_signals"

    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), index=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_instances.id"), index=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    signal_type: Mapped[str] = mapped_column(
        String(32),
        default="repeat_question",
        nullable=False,
        index=True,
        comment="repeat_question/rephrase/abandon/copy_segment/custom",
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
