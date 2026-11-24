"""AIGC 模块端到端冒烟测试。先启动 uvicorn，再运行本脚本。

覆盖：
- 默认 Mock 生成服务 / 提示词模板
- 文生图 → 队列执行 → 素材落库 → 文件可访问
- 素材审核（通过）与审核记录
- 上传源图 → 图生视频
- 文生视频
- 成本与产出统计
- 生成服务连通性测试
"""

import base64
import os
import sys
import time

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=60.0)
SUFFIX = str(int(time.time()))[-6:]


def call(method: str, path: str, token: str | None = None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        print(f"{method} {path} -> {response.status_code} non-JSON")
        sys.exit(1)
    print(f"{method} {path} -> {response.status_code} code={payload.get('code')}")
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(payload)
        sys.exit(1)
    return payload.get("data")


def wait_health(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    print("服务未就绪")
    sys.exit(1)


def wait_job(job_id: int, token: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    detail: dict = {}
    while time.time() < deadline:
        detail = call("GET", f"/api/v1/aigc/generations/{job_id}", token)
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            return detail
        time.sleep(0.3)
    print("等待生成任务超时:", detail.get("status"))
    sys.exit(1)


def main() -> None:
    wait_health()

    login = call(
        "POST",
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    providers = call("GET", "/api/v1/aigc/providers", token)["items"]
    mock = next((item for item in providers if item["provider_type"] == "mock"), None)
    assert mock, providers
    print("providers:", [(item["id"], item["name"], item["provider_type"]) for item in providers])

    templates = call("GET", "/api/v1/aigc/templates", token)["items"]
    assert len(templates) >= 4, templates
    print("templates:", [(item["id"], item["code"], item["category"]) for item in templates])

    poster_template = next(
        (item for item in templates if item["code"] == "aigc_poster_image"), None
    )
    assert poster_template, templates
    render = call(
        "POST",
        f"/api/v1/aigc/templates/{poster_template['id']}/render",
        token,
        json={"values": {"product": "演示手表", "style": "极简科技感"}},
    )
    assert "演示手表" in render["prompt"], render
    assert not render["missing"], render
    print("rendered prompt:", render["prompt"][:60])

    provider_test = call(
        "POST", f"/api/v1/aigc/providers/{mock['id']}/test", token, json={}
    )
    assert provider_test["ok"], provider_test

    # 生成服务 CRUD（用停用的通用 HTTP 服务，避免影响队列）
    extra_provider = call(
        "POST",
        "/api/v1/aigc/providers",
        token,
        json={
            "name": f"冒烟 HTTP 服务-{SUFFIX}",
            "provider_type": "http_generic",
            "base_url": "http://127.0.0.1:9999",
            "api_key": "smoke-secret",
            "supported_types": ["text_to_image"],
            "enabled": False,
            "config": {"create": {"method": "POST", "path": "/generate"}},
        },
    )
    assert extra_provider["has_api_key"], extra_provider
    assert "api_key" not in extra_provider, extra_provider

    updated_provider = call(
        "PATCH",
        f"/api/v1/aigc/providers/{extra_provider['id']}",
        token,
        json={"priority": 55, "description": "冒烟测试"},
    )
    assert updated_provider["priority"] == 55, updated_provider
    call("DELETE", f"/api/v1/aigc/providers/{extra_provider['id']}", token)

    extra_template = call(
        "POST",
        "/api/v1/aigc/templates",
        token,
        json={
            "name": f"冒烟模板-{SUFFIX}",
            "code": f"smoke_template_{SUFFIX}",
            "category": "text_to_image",
            "body": "为「{{product}}」生成一张{{style}}海报",
            "variables": {"product": "默认商品", "style": "极简"},
            "params": {"size": "512x512"},
        },
    )
    rendered = call(
        "POST",
        f"/api/v1/aigc/templates/{extra_template['id']}/render",
        token,
        json={"values": {"product": "冒烟商品"}},
    )
    assert "冒烟商品" in rendered["prompt"], rendered
    call("DELETE", f"/api/v1/aigc/templates/{extra_template['id']}", token)

    # SVG 上传应被拒绝
    svg_response = client.post(
        "/api/v1/aigc/assets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("bad.svg", b"<svg/>", "image/svg+xml")},
    )
    assert svg_response.status_code == 400, svg_response.text
    print("SVG upload rejected:", svg_response.status_code)

    # 文生图
    image_job = call(
        "POST",
        "/api/v1/aigc/generations",
        token,
        json={
            "job_type": "text_to_image",
            "provider_id": mock["id"],
            "prompt": "雨夜咖啡馆，霓虹灯倒映在积水里，电影感构图",
            "negative_prompt": "模糊，低清晰度",
            "params": {"size": "768x512", "count": 2},
        },
    )
    image_job = wait_job(image_job["id"], token)
    assert image_job["status"] == "succeeded", image_job
    assert len(image_job["assets"]) == 2, image_job
    print(
        "image job assets:",
        [(item["id"], item["asset_type"], item["public_url"]) for item in image_job["assets"]],
    )

    for asset in image_job["assets"]:
        response = client.get(asset["public_url"])
        assert response.status_code == 200, asset["public_url"]
        assert response.content.startswith(b"<svg"), asset["public_url"]

    # 审核通过
    asset_id = image_job["assets"][0]["id"]
    review = call(
        "POST",
        f"/api/v1/aigc/assets/{asset_id}/review",
        token,
        json={"decision": "approve", "score": 9, "note": "冒烟测试通过"},
    )
    assert review["asset"]["review_status"] == "approved", review
    reviews = call("GET", f"/api/v1/aigc/assets/{asset_id}/reviews", token)
    assert reviews and reviews[0]["decision"] == "approve", reviews

    # 上传源图 → 图生视频
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    upload = client.post(
        "/api/v1/aigc/assets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("source.png", png_1x1, "image/png")},
    )
    upload_payload = upload.json()
    print("POST /api/v1/aigc/assets/upload ->", upload.status_code)
    assert upload.status_code == 200 and upload_payload.get("code") == 0, upload_payload
    source_asset = upload_payload["data"]

    i2v_job = call(
        "POST",
        "/api/v1/aigc/generations",
        token,
        json={
            "job_type": "image_to_video",
            "provider_id": mock["id"],
            "prompt": "产品缓慢旋转，灯光渐变",
            "input_asset_id": source_asset["id"],
            "params": {"duration": 4},
        },
    )
    i2v_job = wait_job(i2v_job["id"], token)
    assert i2v_job["status"] == "succeeded", i2v_job
    assert i2v_job["assets"] and i2v_job["assets"][0]["asset_type"] == "video", i2v_job

    # 文生视频
    video_job = call(
        "POST",
        "/api/v1/aigc/generations",
        token,
        json={
            "job_type": "text_to_video",
            "provider_id": mock["id"],
            "prompt": "晨光下的桌面，产品缓慢旋转，金属高光流动",
            "params": {"duration": 3, "size": "960x540"},
        },
    )
    video_job = wait_job(video_job["id"], token)
    assert video_job["status"] == "succeeded", video_job
    assert video_job["assets"][0]["duration_seconds"] == 3, video_job

    stats = call("GET", "/api/v1/aigc/stats?days=7", token)
    assert stats["totals"]["jobs"] >= 3, stats
    assert stats["assets"]["total"] >= 4, stats
    print("stats totals:", stats["totals"])
    print("stats assets:", stats["assets"])
    print("AIGC smoke passed.")


if __name__ == "__main__":
    main()
