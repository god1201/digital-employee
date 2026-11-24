"""外部 trainer 端到端冒烟：偏好对 → 导出 → 派发 → 回调。

前置：
- `scripts/trainer_reference.py` 已启动
- `.env` 的 `TRAINING_PROVIDER_URL` 指向该服务
- 后端已重启

运行：
    .venv\\Scripts\\python.exe scripts\\trainer_smoke.py
"""

import os
import sys
import time
import uuid

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
SUFFIX = uuid.uuid4().hex[:6]
client = httpx.Client(timeout=60.0)
token: str | None = None


def call(method: str, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        print(f"{method} {path} -> {response.status_code} non-JSON")
        sys.exit(1)
    print(f"{method} {path} -> {response.status_code}")
    if response.status_code >= 400 or payload.get("code") not in (0, None):
        print(payload)
        sys.exit(1)
    return payload.get("data")


def main() -> None:
    global token
    assert client.get(f"{BASE}/health").status_code == 200

    login = call(
        "POST",
        "/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_code": "demo"},
    )
    token = login["access_token"]

    employee = call(
        "POST",
        "/digital-employees",
        json={
            "name": f"训练冒烟 {SUFFIX}",
            "code": f"train_smoke_{SUFFIX}",
            "position": "测试",
            "status": "active",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "你是测试员工。",
            "config": {},
        },
    )
    suite = call(
        "POST",
        "/evaluation-suites",
        json={
            "employee_id": employee["id"],
            "name": f"训练冒烟套件 {SUFFIX}",
            "code": f"train_suite_{SUFFIX}",
            "threshold": 1.0,
            "regression_tolerance": 0.02,
            "enforce_on_activate": False,
            "enabled": True,
        },
    )
    case = call(
        "POST",
        f"/evaluation-suites/{suite['id']}/cases",
        json={
            "name": "还款日期",
            "case_type": "assertion",
            "input": {},
            "expected": {"exact": "正确还款日期是 45 天"},
            "weight": 1.0,
            "enabled": True,
        },
    )
    call(
        "POST",
        f"/evaluation-suites/{suite['id']}/run",
        json={"outputs": {str(case["id"]): "错误答案"}},
    )

    collected = call(
        "POST",
        "/preference-pairs/collect",
        json={
            "employee_id": employee["id"],
            "sources": ["evaluation"],
            "limit": 10,
        },
    )
    assert collected["created"] >= 1, collected

    exported = call(
        "POST",
        "/preference-pairs/export",
        json={"employee_id": employee["id"]},
    )
    assert exported["count"] >= 1, exported

    job = call(
        "POST",
        "/training-jobs",
        json={
            "employee_id": employee["id"],
            "method": "dpo",
            "dataset_path": exported["path"],
            "config": {"note": "trainer smoke"},
        },
    )
    dispatched = call(
        "POST", f"/training-jobs/{job['id']}/dispatch", json={}
    )
    assert dispatched["status"] == "dispatched", dispatched
    assert dispatched["metrics"]["dispatch"]["external_job_id"], dispatched

    detail = dispatched
    for _ in range(120):
        detail = call("GET", f"/training-jobs/{job['id']}")
        if detail["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(1)
    assert detail["status"] == "succeeded", detail
    metrics = detail["metrics"]
    assert "accuracy" in metrics or "loss" in metrics, detail

    print(
        f"\n外部 trainer 冒烟通过：job #{job['id']}，"
        f"external={metrics['dispatch']['external_job_id']}，"
        f"metrics={ {k: v for k, v in metrics.items() if k != 'dispatch'} }"
    )


if __name__ == "__main__":
    main()
