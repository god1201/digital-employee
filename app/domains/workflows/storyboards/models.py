from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, IdMixin, TenantMixin, TimestampMixin


class StoryboardProject(IdMixin, TenantMixin, TimestampMixin, Base):
    """一次 AI 剧本 → 分镜项目。"""

    __tablename__ = "storyboard_projects"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    genre: Mapped[str] = mapped_column(String(64), default="短剧", nullable=False)
    style: Mapped[str] = mapped_column(String(128), default="写实电影感", nullable=False)
    script: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        nullable=False,
        comment="draft/generating/ready/failed",
    )
    scene_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shot_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)


class StoryboardScene(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "storyboard_scenes"

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("storyboard_projects.id"), index=True, nullable=False
    )
    scene_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    characters: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mood: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class StoryboardShot(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "storyboard_shots"

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("storyboard_projects.id"), index=True, nullable=False
    )
    scene_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("storyboard_scenes.id"), index=True, nullable=False
    )
    shot_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    shot_type: Mapped[str] = mapped_column(String(32), default="中景", nullable=False)
    camera_movement: Mapped[str] = mapped_column(String(32), default="固定", nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    audio_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
