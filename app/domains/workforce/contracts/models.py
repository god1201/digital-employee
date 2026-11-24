from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class JobContract(IdMixin, TenantMixin, TimestampMixin, Base):
    """岗位职责契约。

    契约层是安全底线：只能由人修改，Agent 不得自行提权或删除 must_ask。
    """

    __tablename__ = "job_contracts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", name="uq_job_contracts_employee"),
    )

    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("digital_employees.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    can_do: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="职责清单：可以做"
    )
    cannot_do: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="职责清单：不能做（硬性红线）"
    )
    must_ask: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="必须请示的事项"
    )
    kpi: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    report_to: Mapped[str | None] = mapped_column(String(128))
    report_freq: Mapped[str | None] = mapped_column(String(128))
    work_hours: Mapped[str | None] = mapped_column(String(128))
    escalation_path: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="升级路径，按顺序排列"
    )
    autonomy_level: Mapped[str] = mapped_column(
        String(8), default="L2", nullable=False, comment="L0/L1/L2/L3"
    )
    autonomy_overrides: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment='按能力覆盖自主权，如 {"tool:send_email": "L1"}',
    )
    red_lines: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment=(
            "权限红线：read_only/forbidden_tools/allowed_tools/"
            "amount_threshold/count_threshold/sandbox_required"
        ),
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, comment="draft/active/archived"
    )
    created_by: Mapped[int | None] = mapped_column(Integer)
