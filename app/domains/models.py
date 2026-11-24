"""全部 ORM 模型，导入此处以便 Base.metadata 完整注册。"""

from app.domains.governance.access.models import AccessRule, Authorization
from app.domains.governance.audit.models import AuditLog
from app.domains.governance.quality.models import (
    HallucinationCheck,
    InspectionRecord,
    InspectionRule,
)
from app.domains.governance.risk.models import RiskCheck, RiskRule
from app.domains.identity.models import Tenant, User
from app.domains.knowledge.models import (
    GraphEntity,
    GraphRelation,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    MultimodalExtraction,
)
from app.domains.learning.models import (
    EmployeeTrial,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    FailureAttribution,
    FeedbackSample,
    FewShotExample,
    ImplicitSignal,
    InterventionDelta,
    LearningArtifact,
    LearningQuestion,
    OutcomeEvent,
    PreferenceMemory,
    PreferencePair,
    TrainingJob,
    WeeklyReview,
)
from app.domains.operations.models import AlertEvent, AlertRule, WorkerHeartbeat
from app.domains.skills.agents.models import Agent
from app.domains.skills.marketplace.models import EmployeeSkill, SkillPackage
from app.domains.skills.mcp.models import MCPServer
from app.domains.skills.registry.models import ApiRegistry
from app.domains.skills.tools.models import Tool
from app.domains.workflows.aigc.models import (
    AigcAsset,
    AigcJob,
    AigcPromptTemplate,
    AigcProvider,
    AigcReview,
)
from app.domains.workflows.approvals.models import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalForm,
    ApprovalInstance,
    ApprovalNotification,
    ApprovalTask,
)
from app.domains.workflows.storyboards.models import (
    StoryboardProject,
    StoryboardScene,
    StoryboardShot,
)
from app.domains.workflows.tasks.models import (
    TaskDefinition,
    TaskInstance,
    TaskStep,
    TaskTrigger,
)
from app.domains.workforce.collaboration.models import CollaborationRun
from app.domains.workforce.contracts.models import JobContract
from app.domains.workforce.conversations.models import (
    ChatMessage,
    Conversation,
    ConversationMember,
)
from app.domains.workforce.employees.models import DigitalEmployee
from app.domains.workforce.migrations.models import CapabilityMigration
from app.domains.workforce.persona.models import PersonaProfile
from app.domains.workforce.projects.models import Project, ProjectMember
from app.domains.workforce.teams.models import RolePreset, Team, TeamMember, TeamTemplate
from app.domains.workforce.templates.models import JobTemplate

__all__ = [
    "Tenant",
    "User",
    "DigitalEmployee",
    "JobContract",
    "InterventionDelta",
    "LearningArtifact",
    "PreferenceMemory",
    "FailureAttribution",
    "EvaluationSuite",
    "EvaluationCase",
    "EvaluationRun",
    "EmployeeTrial",
    "LearningQuestion",
    "WeeklyReview",
    "PreferencePair",
    "TrainingJob",
    "CollaborationRun",
    "CapabilityMigration",
    "PersonaProfile",
    "Project",
    "ProjectMember",
    "Conversation",
    "ConversationMember",
    "ChatMessage",
    "FewShotExample",
    "OutcomeEvent",
    "JobTemplate",
    "MultimodalExtraction",
    "ImplicitSignal",
    "AigcProvider",
    "AigcPromptTemplate",
    "AigcJob",
    "AigcAsset",
    "AigcReview",
    "ApprovalForm",
    "ApprovalFlow",
    "ApprovalInstance",
    "ApprovalTask",
    "ApprovalAction",
    "ApprovalNotification",
    "Authorization",
    "AccessRule",
    "ApiRegistry",
    "Agent",
    "MCPServer",
    "SkillPackage",
    "EmployeeSkill",
    "WorkerHeartbeat",
    "AlertRule",
    "AlertEvent",
    "KnowledgeBase",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "GraphEntity",
    "GraphRelation",
    "RiskRule",
    "RiskCheck",
    "InspectionRule",
    "InspectionRecord",
    "HallucinationCheck",
    "StoryboardProject",
    "StoryboardScene",
    "StoryboardShot",
    "RolePreset",
    "TeamTemplate",
    "Team",
    "TeamMember",
    "Tool",
    "TaskDefinition",
    "TaskInstance",
    "TaskStep",
    "TaskTrigger",
    "AuditLog",
    "FeedbackSample",
]
