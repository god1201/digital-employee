"""AIGC 默认数据：每个租户内置一个 Mock 生成服务和几套提示词模板。"""

import logging

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domains.identity.models import Tenant
from app.domains.workflows.aigc.models import AigcPromptTemplate, AigcProvider
from app.domains.workflows.aigc.providers import SUPPORTED_JOB_TYPES

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES = [
    {
        "name": "商品海报（文生图）",
        "code": "aigc_poster_image",
        "category": "text_to_image",
        "body": (
            "为「{{product}}」生成一张{{style}}风格的商品海报，画面主体居中，"
            "柔和棚拍光，干净背景，高清细节，商业摄影，适合电商详情页主图。"
        ),
        "negative_prompt": "低清晰度，模糊，变形，文字水印，杂乱背景",
        "variables": {"product": "智能手表", "style": "极简科技感"},
        "params": {"size": "1024x1024", "count": 1},
        "description": "电商商品海报，替换 product 与 style 即可复用。",
    },
    {
        "name": "氛围场景（文生图）",
        "code": "aigc_scene_image",
        "category": "text_to_image",
        "body": (
            "{{scene}}，{{style}}风格，电影感构图，体积光，细节丰富，"
            "画面干净，适合作为短视频封面或分镜概念图。"
        ),
        "negative_prompt": "过度曝光，畸变，噪点，低分辨率",
        "variables": {
            "scene": "雨夜霓虹街道，行人撑伞走过，地面积水倒映灯光",
            "style": "写实电影感",
        },
        "params": {"size": "1024x576", "count": 1},
        "description": "短视频封面 / 分镜概念图。",
    },
    {
        "name": "产品短片（文生视频）",
        "code": "aigc_product_video",
        "category": "text_to_video",
        "body": (
            "一段{{duration}}秒{{style}}风格的短片：{{scene}}，"
            "镜头{{camera}}，光影自然，画面稳定，主体清晰，适合品牌宣传。"
        ),
        "negative_prompt": "画面抖动，闪烁，主体变形，低清晰度",
        "variables": {
            "duration": "5",
            "style": "商业广告质感",
            "scene": "晨光下的桌面，产品缓慢旋转，金属高光流动",
            "camera": "缓慢推进",
        },
        "params": {"duration": 5, "size": "1280x720"},
        "description": "品牌产品宣传短片。",
    },
    {
        "name": "图片动起来（图生视频）",
        "code": "aigc_image_to_video",
        "category": "image_to_video",
        "body": (
            "基于输入图片生成{{duration}}秒短视频：{{motion}}，"
            "保持主体一致，镜头平稳，{{style}}。"
        ),
        "negative_prompt": "主体变形，闪烁，画面撕裂，低清晰度",
        "variables": {
            "duration": "5",
            "motion": "产品缓慢旋转，灯光渐变，背景轻微虚化",
            "style": "商业广告质感",
        },
        "params": {"duration": 5},
        "description": "输入一张产品图，生成轻微的运镜与光影变化。",
    },
]


async def seed_aigc_defaults() -> None:
    """幂等初始化：已有同名服务或同编码模板时跳过。"""
    async with SessionLocal() as session:
        tenant_ids = list((await session.scalars(select(Tenant.id))).all())
        if not tenant_ids:
            return

        created_providers = 0
        created_templates = 0
        for tenant_id in tenant_ids:
            provider_count = await session.scalar(
                select(func.count())
                .select_from(AigcProvider)
                .where(AigcProvider.tenant_id == tenant_id)
            )
            if not provider_count:
                session.add(
                    AigcProvider(
                        tenant_id=tenant_id,
                        name="内置 Mock 生成服务",
                        provider_type="mock",
                        model="mock-svg-v1",
                        supported_types=list(SUPPORTED_JOB_TYPES),
                        enabled=True,
                        is_default=True,
                        priority=10,
                        cost_per_unit=0.0,
                        cost_unit="image",
                        timeout_seconds=30,
                        description="无需外部 Key 的占位生成服务，用于流程演示与联调。",
                    )
                )
                created_providers += 1

            existing_codes = set(
                (
                    await session.scalars(
                        select(AigcPromptTemplate.code).where(
                            AigcPromptTemplate.tenant_id == tenant_id
                        )
                    )
                ).all()
            )
            for item in DEFAULT_TEMPLATES:
                if item["code"] in existing_codes:
                    continue
                session.add(AigcPromptTemplate(tenant_id=tenant_id, **item))
                created_templates += 1

        await session.commit()

    if created_providers or created_templates:
        logger.info(
            "AIGC 默认数据初始化完成：%s 个生成服务，%s 个提示词模板",
            created_providers,
            created_templates,
        )
