"""数据维护：过期提问、旧 Worker 心跳、可选审计与训练文件清理。

默认 dry-run，只打印将处理的数量；确认后加 --apply。

    .venv\\Scripts\\python.exe scripts\\maintenance.py
    .venv\\Scripts\\python.exe scripts\\maintenance.py --apply

可选：
    --heartbeat-days 7     清理超过 N 天未见的 Worker 心跳（默认 7，0 关闭）
    --audit-days 180       删除超过 N 天的审计日志（默认 0 关闭）
    --training-days 30     删除 data/training 下超过 N 天且未被训练任务引用的文件
"""

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, update

from app.core.base import utcnow
from app.core.database import SessionLocal, engine
from app.core.logging import setup_logging
from app.domains.governance.audit.models import AuditLog
from app.domains.learning.models import (
    LearningArtifact,
    LearningQuestion,
    PreferenceMemory,
    TrainingJob,
)
from app.domains.operations.models import WorkerHeartbeat

TRAINING_DIR = Path("data/training")


async def run(apply: bool, heartbeat_days: int, audit_days: int, training_days: int) -> None:
    now = utcnow()
    async with SessionLocal() as session:
        expired = await session.scalar(
            select(func.count(LearningQuestion.id)).where(
                LearningQuestion.status == "open",
                LearningQuestion.expires_at.is_not(None),
                LearningQuestion.expires_at < now,
            )
        )
        print(f"过期提问: {expired or 0}")
        if apply and expired:
            await session.execute(
                update(LearningQuestion)
                .where(
                    LearningQuestion.status == "open",
                    LearningQuestion.expires_at.is_not(None),
                    LearningQuestion.expires_at < now,
                )
                .values(status="expired")
            )

        expired_memories = (
            await session.scalar(
                select(func.count(PreferenceMemory.id)).where(
                    PreferenceMemory.status == "active",
                    PreferenceMemory.expires_at.is_not(None),
                    PreferenceMemory.expires_at < now,
                )
            )
            or 0
        )
        print(f"过期偏好记忆: {expired_memories}")
        if apply and expired_memories:
            await session.execute(
                update(PreferenceMemory)
                .where(
                    PreferenceMemory.status == "active",
                    PreferenceMemory.expires_at.is_not(None),
                    PreferenceMemory.expires_at < now,
                )
                .values(status="archived")
            )

        expired_artifacts = (
            await session.scalar(
                select(func.count(LearningArtifact.id)).where(
                    LearningArtifact.status.in_(
                        ["pending_approval", "approved", "active", "canary"]
                    ),
                    LearningArtifact.expires_at.is_not(None),
                    LearningArtifact.expires_at < now,
                )
            )
            or 0
        )
        print(f"过期待处理/生效工件: {expired_artifacts}")
        if apply and expired_artifacts:
            await session.execute(
                update(LearningArtifact)
                .where(
                    LearningArtifact.status.in_(
                        ["pending_approval", "approved", "active", "canary"]
                    ),
                    LearningArtifact.expires_at.is_not(None),
                    LearningArtifact.expires_at < now,
                )
                .values(status="archived")
            )

        stale_workers = 0
        if heartbeat_days > 0:
            cutoff = now - timedelta(days=heartbeat_days)
            stale_workers = (
                await session.scalar(
                    select(func.count(WorkerHeartbeat.id)).where(
                        WorkerHeartbeat.last_seen_at < cutoff
                    )
                )
                or 0
            )
            print(f"过期 Worker 心跳: {stale_workers}")
            if apply and stale_workers:
                await session.execute(
                    delete(WorkerHeartbeat).where(
                        WorkerHeartbeat.last_seen_at < cutoff
                    )
                )

        old_audits = 0
        if audit_days > 0:
            cutoff = now - timedelta(days=audit_days)
            old_audits = (
                await session.scalar(
                    select(func.count(AuditLog.id)).where(AuditLog.created_at < cutoff)
                )
                or 0
            )
            print(f"过期审计日志: {old_audits}")
            if apply and old_audits:
                await session.execute(
                    delete(AuditLog).where(AuditLog.created_at < cutoff)
                )
                print("警告：审计日志已删除，请确认合规保留期")

        stale_files = 0
        if training_days > 0 and TRAINING_DIR.is_dir():
            cutoff = now - timedelta(days=training_days)
            referenced = set(
                (
                    await session.scalars(select(TrainingJob.dataset_path))
                ).all()
            )
            for path in TRAINING_DIR.glob("*.jsonl"):
                if path.stat().st_mtime >= cutoff.timestamp():
                    continue
                if str(path.resolve()) in referenced or str(path) in referenced:
                    continue
                stale_files += 1
                print(f"待清理训练文件: {path}")
                if apply:
                    path.unlink()
        print(f"过期训练文件: {stale_files}")

        if apply:
            await session.commit()
            print("已应用清理")
        else:
            await session.rollback()
            print("dry-run：未修改数据（加 --apply 执行）")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="数字员工平台数据维护")
    parser.add_argument("--apply", action="store_true", help="实际执行清理")
    parser.add_argument("--heartbeat-days", type=int, default=7)
    parser.add_argument("--audit-days", type=int, default=0)
    parser.add_argument("--training-days", type=int, default=0)
    args = parser.parse_args()

    setup_logging()
    asyncio.run(
        run(
            args.apply,
            args.heartbeat_days,
            args.audit_days,
            args.training_days,
        )
    )


if __name__ == "__main__":
    main()
