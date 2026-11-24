import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.domains.workflows.aigc.jobs import build_prompt
from app.domains.workflows.aigc.models import AigcAsset, AigcJob
from app.domains.workflows.aigc.providers import (
    MockProvider,
    estimate_cost,
    missing_placeholders,
    parse_size,
    render_placeholders,
)
from app.domains.workflows.aigc.schemas import AssetOut, GenerationOut


def _provider_row(**overrides):
    values = {
        "id": 1,
        "name": "mock",
        "provider_type": "mock",
        "api_key_encrypted": None,
        "config": {},
        "supported_types": ["text_to_image", "text_to_video", "image_to_video"],
        "model": "mock",
        "timeout_seconds": 30,
        "cost_per_unit": 0.5,
        "cost_unit": "image",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_placeholder_rendering() -> None:
    assert render_placeholders("{{product}} / {{style}}", {"product": "手表"}) == "手表 / {{style}}"
    assert missing_placeholders("{{product}} / {{style}}") == ["product", "style"]
    assert render_placeholders("{{a}}", {"a": 1}) == "1"


def test_template_prompt_build() -> None:
    template = SimpleNamespace(
        variables={"product": "默认商品"},
        body="为「{{product}}」生成海报，{{style}}",
        negative_prompt="模糊",
    )
    prompt, negative = build_prompt(template, None, None, {"style": "极简"})
    assert prompt == "为「默认商品」生成海报，极简"
    assert negative == "模糊"

    prompt, negative = build_prompt(template, "自定义提示词", "", {})
    assert prompt == "自定义提示词"
    assert negative == "模糊"


def test_size_and_cost() -> None:
    assert parse_size({"size": "800x600"}) == (800, 600)
    assert parse_size({"size": "bad"}) == (1024, 1024)
    row = _provider_row()
    assert estimate_cost(row, "text_to_image", {"count": 3}) == 1.5
    row = _provider_row(cost_unit="second", cost_per_unit=0.2)
    assert estimate_cost(row, "text_to_video", {"duration": 5}) == 1.0
    row = _provider_row(cost_unit="request", cost_per_unit=0.1)
    assert estimate_cost(row, "image_to_video", {}) == 0.1


def test_mock_provider_generates_media() -> None:
    provider = MockProvider(_provider_row())
    images = asyncio.run(
        provider.generate(
            job_type="text_to_image",
            prompt="雨夜咖啡馆",
            negative_prompt="",
            params={"count": 2, "size": "640x480"},
        )
    )
    assert len(images) == 2
    assert images[0].mime_type == "image/svg+xml"
    assert images[0].width == 640
    assert b"<svg" in images[0].data
    assert "雨夜咖啡馆" in images[0].data.decode("utf-8")

    videos = asyncio.run(
        provider.generate(
            job_type="text_to_video",
            prompt="产品缓慢旋转",
            negative_prompt="",
            params={"duration": 6},
        )
    )
    assert len(videos) == 1
    assert videos[0].duration_seconds == 6.0
    assert videos[0].metadata["mock"] is True


def test_job_and_asset_serialization() -> None:
    now = datetime.now(UTC)
    job = AigcJob(
        id=1,
        tenant_id=1,
        provider_id=1,
        template_id=None,
        employee_id=None,
        job_type="text_to_image",
        prompt="test",
        negative_prompt="",
        params={},
        status="pending",
        priority=100,
        attempt=0,
        max_attempts=2,
        risk={},
        estimated_cost=0.0,
        cost=0.0,
        latency_ms=0,
        result={},
        created_at=now,
        updated_at=now,
    )
    payload = GenerationOut.model_validate(job).model_dump(mode="json")
    assert payload["status"] == "pending"
    assert payload["assets"] == []

    asset = AigcAsset(
        id=1,
        tenant_id=1,
        job_id=1,
        asset_type="image",
        source="generated",
        public_url="/media/1/202601/a.svg",
        mime_type="image/svg+xml",
        size_bytes=10,
        prompt="test",
        negative_prompt="",
        review_status="pending",
        review_note="",
        tags=[],
        metadata_={"mock": True},
        created_at=now,
        updated_at=now,
    )
    asset_payload = AssetOut.model_validate(asset).model_dump(mode="json")
    assert asset_payload["metadata"] == {"mock": True}
    assert asset_payload["review_status"] == "pending"
