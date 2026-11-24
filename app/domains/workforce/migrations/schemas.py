from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel

MigrationComponent = Literal["skills", "artifacts", "preferences", "contract"]


class CapabilityMigrationCreate(BaseModel):
    source_employee_id: int
    target_employee_id: int
    components: list[MigrationComponent] = Field(
        default_factory=lambda: ["skills", "artifacts", "preferences"]
    )
    dry_run: bool = False


class CapabilityMigrationOut(ORMModel):
    id: int
    tenant_id: int
    source_employee_id: int
    target_employee_id: int
    components: list
    dry_run: bool
    status: str
    report: dict
    created_at: datetime
