"""AI 剧本 → 分镜：提示词、结果归一化与校验。"""

from app.core.llm import LLMError, chat_json, is_configured

MAX_SCENES = 8
MAX_SHOTS_PER_SCENE = 6
MAX_TOTAL_SHOTS = 50


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        cleaned = value.replace("、", ",").replace("，", ",")
        return [item.strip() for item in cleaned.split(",") if item.strip()]
    return []


def _clamp_duration(value) -> int:
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        duration = 3
    return max(1, min(duration, 30))


def normalize_storyboard(data: dict, style: str = "") -> dict:
    if not isinstance(data, dict):
        raise LLMError("分镜结果不是 JSON 对象")

    raw_scenes = data.get("scenes")
    if raw_scenes is None and isinstance(data.get("storyboard"), dict):
        raw_scenes = data["storyboard"].get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise LLMError("分镜结果缺少 scenes")

    scenes: list[dict] = []
    total_shots = 0

    for scene_position, raw_scene in enumerate(raw_scenes[:MAX_SCENES], start=1):
        if not isinstance(raw_scene, dict):
            continue
        raw_shots = raw_scene.get("shots")
        if not isinstance(raw_shots, list):
            raw_shots = []

        shots: list[dict] = []
        for shot_position, raw_shot in enumerate(raw_shots[:MAX_SHOTS_PER_SCENE], start=1):
            if total_shots >= MAX_TOTAL_SHOTS:
                break
            if not isinstance(raw_shot, dict):
                continue

            description = str(raw_shot.get("description") or raw_shot.get("visual") or "").strip()
            image_prompt = str(raw_shot.get("image_prompt") or raw_shot.get("prompt") or "").strip()
            if not image_prompt:
                image_prompt = f"{description}，{style}".strip("，")

            shots.append(
                {
                    "shot_index": shot_position,
                    "shot_type": str(raw_shot.get("shot_type") or raw_shot.get("type") or "中景")[
                        :32
                    ],
                    "camera_movement": str(
                        raw_shot.get("camera_movement") or raw_shot.get("movement") or "固定"
                    )[:32],
                    "duration_seconds": _clamp_duration(
                        raw_shot.get("duration_seconds") or raw_shot.get("duration")
                    ),
                    "dialogue": str(raw_shot.get("dialogue") or "").strip(),
                    "description": description,
                    "image_prompt": image_prompt,
                    "audio_note": str(
                        raw_shot.get("audio_note") or raw_shot.get("audio") or ""
                    ).strip(),
                }
            )
            total_shots += 1

        if not shots:
            continue

        scenes.append(
            {
                "scene_index": scene_position,
                "location": str(raw_scene.get("location") or "")[:255],
                "time_of_day": str(raw_scene.get("time_of_day") or raw_scene.get("time") or "")[
                    :64
                ],
                "characters": _as_list(raw_scene.get("characters")),
                "summary": str(raw_scene.get("summary") or "").strip(),
                "mood": str(raw_scene.get("mood") or "")[:128],
                "shots": shots,
            }
        )

    if not scenes:
        raise LLMError("分镜结果为空")
    return {"scenes": scenes}


async def generate_storyboard(project) -> tuple[dict, int]:
    if not is_configured():
        raise LLMError("未配置 LLM_API_KEY，无法生成分镜")

    messages = [
        {
            "role": "system",
            "content": (
                "你是专业影视分镜师。请把剧本拆解为场景和镜头，只输出 JSON，不要输出解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"项目：{project.title}\n"
                f"类型：{project.genre}\n"
                f"风格：{project.style}\n"
                f"剧本：\n{project.script}\n\n"
                "要求：最多 5 个场景，每个场景最多 4 个镜头，每个镜头 2-10 秒。"
                "输出 JSON：\n"
                '{"scenes":[{"location":"地点","time_of_day":"日/夜",'
                '"characters":["角色"],"summary":"场景概述","mood":"氛围",'
                '"shots":[{"shot_type":"远景/全景/中景/近景/特写",'
                '"camera_movement":"固定/推/拉/摇/移/跟/升降",'
                '"duration_seconds":3,"dialogue":"台词或空",'
                '"description":"画面描述","image_prompt":"AIGC 画面提示词",'
                '"audio_note":"音乐/音效"}]}]}'
            ),
        },
    ]

    data, tokens = await chat_json(messages, timeout=120)
    normalized = normalize_storyboard(data, project.style)
    return normalized, tokens


def storyboard_to_csv(project, scenes: list[dict]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "项目",
            "场景",
            "地点",
            "时间",
            "角色",
            "场景概述",
            "氛围",
            "镜头",
            "景别",
            "运镜",
            "时长(秒)",
            "台词",
            "画面描述",
            "画面提示词",
            "音乐/音效",
        ]
    )
    for scene in scenes:
        for shot in scene.get("shots", []):
            writer.writerow(
                [
                    project.title,
                    scene.get("scene_index"),
                    scene.get("location"),
                    scene.get("time_of_day"),
                    "、".join(scene.get("characters") or []),
                    scene.get("summary"),
                    scene.get("mood"),
                    shot.get("shot_index"),
                    shot.get("shot_type"),
                    shot.get("camera_movement"),
                    shot.get("duration_seconds"),
                    shot.get("dialogue"),
                    shot.get("description"),
                    shot.get("image_prompt"),
                    shot.get("audio_note"),
                ]
            )
    return buffer.getvalue()
