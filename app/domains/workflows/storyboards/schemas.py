from datetime import datetime

from pydantic import BaseModel, Field

from app.core.schema_common import ORMModel


class StoryboardCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    genre: str = Field(default="短剧", max_length=64)
    style: str = Field(default="写实电影感", max_length=128)
    script: str = Field(min_length=10)


class StoryboardUpdate(BaseModel):
    title: str | None = None
    genre: str | None = None
    style: str | None = None
    script: str | None = None


class ShotOut(ORMModel):
    id: int
    project_id: int
    scene_id: int
    shot_index: int
    shot_type: str
    camera_movement: str
    duration_seconds: int
    dialogue: str
    description: str
    image_prompt: str
    audio_note: str


class SceneOut(ORMModel):
    id: int
    project_id: int
    scene_index: int
    location: str
    time_of_day: str
    characters: list
    summary: str
    mood: str
    shots: list[ShotOut] = Field(default_factory=list)


class StoryboardOut(ORMModel):
    id: int
    tenant_id: int
    title: str
    genre: str
    style: str
    status: str
    scene_count: int
    shot_count: int
    tokens: int
    model: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class StoryboardDetail(StoryboardOut):
    script: str
    scenes: list[SceneOut] = Field(default_factory=list)
