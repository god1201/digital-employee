from fastapi import APIRouter

from app.core.config import settings
from app.core.response import success
from app.domains.governance.access.authorizations_router import router as authorizations_router
from app.domains.governance.access.rules_router import router as access_rules_router
from app.domains.governance.audit.router import router as audit_router
from app.domains.governance.quality.hallucination_router import (
    router as hallucination_router,
)
from app.domains.governance.quality.router import router as qa_router
from app.domains.governance.risk.router import router as risk_router
from app.domains.identity.router import router as auth_router
from app.domains.knowledge.documents_router import (
    router as knowledge_documents_router,
)
from app.domains.knowledge.multimodal_router import router as multimodal_router
from app.domains.knowledge.router import router as knowledge_router
from app.domains.learning.artifacts_router import router as artifacts_router
from app.domains.learning.attributions_router import router as attributions_router
from app.domains.learning.evaluations_router import router as evaluations_router
from app.domains.learning.implicit_router import router as implicit_router
from app.domains.learning.interventions_router import router as interventions_router
from app.domains.learning.memory_router import router as memory_router
from app.domains.learning.onboarding_router import router as onboarding_router
from app.domains.learning.outcomes_router import router as outcomes_router
from app.domains.learning.p2_router import router as p2_router
from app.domains.learning.preferences_router import router as preferences_router
from app.domains.learning.router import router as feedback_router
from app.domains.learning.training_router import router as training_router
from app.domains.learning.trials_router import router as trials_router
from app.domains.operations.alerts_router import router as alerts_router
from app.domains.operations.monitoring_router import router as monitoring_router
from app.domains.skills.agents.router import router as agents_router
from app.domains.skills.marketplace.router import router as marketplace_router
from app.domains.skills.mcp.router import router as mcp_router
from app.domains.skills.registry.router import router as registry_router
from app.domains.skills.tools.router import router as tools_router
from app.domains.workflows.aigc.router import router as aigc_router
from app.domains.workflows.approvals.router import router as approvals_router
from app.domains.workflows.storyboards.router import router as storyboards_router
from app.domains.workflows.tasks.router import router as tasks_router
from app.domains.workflows.tasks.triggers_router import router as triggers_router
from app.domains.workforce.collaboration.router import router as collaboration_router
from app.domains.workforce.contracts.router import router as contracts_router
from app.domains.workforce.conversations.router import router as conversations_router
from app.domains.workforce.employees.router import router as employees_router
from app.domains.workforce.migrations.router import router as migration_router
from app.domains.workforce.persona.router import router as persona_router
from app.domains.workforce.projects.router import router as projects_router
from app.domains.workforce.routing_router import router as routing_router
from app.domains.workforce.teams.router import router as teams_router
from app.domains.workforce.templates.router import router as job_templates_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(employees_router)
api_router.include_router(projects_router)
api_router.include_router(conversations_router)
api_router.include_router(contracts_router)
api_router.include_router(persona_router)
api_router.include_router(routing_router)
api_router.include_router(job_templates_router)
api_router.include_router(authorizations_router)
api_router.include_router(access_rules_router)
api_router.include_router(registry_router)
api_router.include_router(tools_router)
api_router.include_router(mcp_router)
api_router.include_router(marketplace_router)
api_router.include_router(agents_router)
api_router.include_router(monitoring_router)
api_router.include_router(alerts_router)
api_router.include_router(knowledge_router)
api_router.include_router(knowledge_documents_router)
api_router.include_router(multimodal_router)
api_router.include_router(risk_router)
api_router.include_router(qa_router)
api_router.include_router(hallucination_router)
api_router.include_router(storyboards_router)
api_router.include_router(aigc_router)
api_router.include_router(approvals_router)
api_router.include_router(teams_router)
api_router.include_router(tasks_router)
api_router.include_router(triggers_router)
api_router.include_router(feedback_router)
api_router.include_router(preferences_router)
api_router.include_router(interventions_router)
api_router.include_router(artifacts_router)
api_router.include_router(attributions_router)
api_router.include_router(evaluations_router)
api_router.include_router(trials_router)
api_router.include_router(p2_router)
api_router.include_router(memory_router)
api_router.include_router(onboarding_router)
api_router.include_router(outcomes_router)
api_router.include_router(implicit_router)
api_router.include_router(training_router)
api_router.include_router(collaboration_router)
api_router.include_router(migration_router)
api_router.include_router(audit_router)


@api_router.get("", tags=["系统"], summary="API 索引")
async def api_index() -> dict:
    prefix = settings.api_prefix
    return success(
        {
            "prefix": prefix,
            "docs": "/docs",
            "modules": {
                "auth": f"{prefix}/auth",
                "employees": f"{prefix}/digital-employees",
                "job_contracts": f"{prefix}/digital-employees/{{employee_id}}/contract",
                "authorizations": f"{prefix}/authorizations",
                "access_rules": f"{prefix}/access-rules",
                "api_registry": f"{prefix}/api-registries",
                "tools": f"{prefix}/tools",
                "mcp_servers": f"{prefix}/mcp-servers",
                "skill_packages": f"{prefix}/skill-packages",
                "employee_skills": f"{prefix}/digital-employees/{{employee_id}}/skills",
                "agents": f"{prefix}/agents",
                "agent_employees": (
                    f"{prefix}/agents/{{agent_id}}/employees"
                ),
                "monitoring": f"{prefix}/monitoring",
                "alerts": f"{prefix}/alert-rules",
                "knowledge": f"{prefix}/knowledge-bases",
                "knowledge_documents": f"{prefix}/knowledge-documents",
                "multimodal": f"{prefix}/multimodal",
                "implicit_signals": f"{prefix}/implicit-signals",
                "risk": f"{prefix}/risk",
                "qa": f"{prefix}/qa",
                "hallucination": f"{prefix}/hallucination",
                "storyboards": f"{prefix}/storyboards",
                "aigc": f"{prefix}/aigc",
                "approvals": f"{prefix}/approvals",
                "team_templates": f"{prefix}/team-templates",
                "teams": f"{prefix}/teams",
                "tasks": f"{prefix}/tasks",
                "task_triggers": f"{prefix}/task-triggers",
                "feedback": f"{prefix}/feedback",
                "preferences": f"{prefix}/preferences",
                "interventions": f"{prefix}/interventions",
                "learning_artifacts": f"{prefix}/learning-artifacts",
                "attributions": f"{prefix}/attributions",
                "evaluation_suites": f"{prefix}/evaluation-suites",
                "evaluation_runs": f"{prefix}/evaluation-runs",
                "trials": f"{prefix}/digital-employees/{{employee_id}}/trials",
                "employee_profile": f"{prefix}/digital-employees/{{employee_id}}/profile",
                "employee_trend": (
                    f"{prefix}/digital-employees/{{employee_id}}/profile/trend"
                ),
                "employee_workbench": (
                    f"{prefix}/digital-employees/{{employee_id}}/workbench"
                ),
                "employee_token_usage": (
                    f"{prefix}/digital-employees/{{employee_id}}/token-usage"
                ),
                "employee_token_export": (
                    f"{prefix}/digital-employees/{{employee_id}}/token-usage/export"
                ),
                "projects": f"{prefix}/projects",
                "conversations": f"{prefix}/conversations",
                "conversation_tasks": (
                    f"{prefix}/conversations/{{conversation_id}}/tasks"
                ),
                "conversation_stream": (
                    f"{prefix}/conversations/{{conversation_id}}/messages/stream"
                ),
                "conversation_attachments": (
                    f"{prefix}/conversations/{{conversation_id}}/attachments"
                ),
                "learning_questions": f"{prefix}/learning-questions",
                "learning_jobs": f"{prefix}/learning/jobs/daily-batch",
                "weekly_reviews": f"{prefix}/weekly-reviews",
                "expert_trajectories": f"{prefix}/expert-trajectories",
                "timeline": f"{prefix}/timeline",
                "preference_pairs": f"{prefix}/preference-pairs",
                "training_jobs": f"{prefix}/training-jobs",
                "collaborations": f"{prefix}/collaborations",
                "capability_migrations": f"{prefix}/capability-migrations",
                "persona": f"{prefix}/digital-employees/{{employee_id}}/persona",
                "memories": f"{prefix}/digital-employees/{{employee_id}}/memories",
                "few_shot_examples": (
                    f"{prefix}/digital-employees/{{employee_id}}/few-shot-examples"
                ),
                "onboarding": f"{prefix}/digital-employees/{{employee_id}}/onboarding",
                "routing": f"{prefix}/digital-employees/{{employee_id}}/routing",
                "outcome_events": f"{prefix}/outcome-events",
                "job_templates": f"{prefix}/job-templates",
                "audit": f"{prefix}/audit-logs",
            },
        }
    )
