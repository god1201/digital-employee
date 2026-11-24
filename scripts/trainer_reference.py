"""参考外部 trainer：接收 DPO/SFT 数据集、返回 job_id，并回调平台状态。

仅用于联调，不执行真实训练。真实 trainer 只需实现同样的 HTTP 契约：
- 接收 `POST <TRAINING_PROVIDER_URL>` 的 JSON 数据集与 `callback_token`
- 返回 2xx JSON，可带 `job_id`
- 用 `X-Training-Token: <callback_token>` 回调
  `POST /api/v1/training-jobs/{job_id}/status`

运行：
    .venv\\Scripts\\python.exe scripts\\trainer_reference.py

环境变量：
    TRAINER_PORT=9100
    PLATFORM_BASE_URL=http://127.0.0.1:8000
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.getenv("TRAINER_PORT", "9100"))


def _callback(job_id: int, token: str, external_id: str) -> None:
    url = f"{PLATFORM_BASE_URL}/api/v1/training-jobs/{job_id}/status"
    headers = {"X-Training-Token": token}
    try:
        time.sleep(1)
        response = httpx.post(
            url,
            headers=headers,
            json={"status": "running", "metrics": {"epoch": 1}},
            timeout=30,
        )
        print(f"[callback] job={job_id} running -> {response.status_code}", flush=True)
        time.sleep(1)
        response = httpx.post(
            url,
            headers=headers,
            json={
                "status": "succeeded",
                "metrics": {
                    "loss": 0.12,
                    "accuracy": 0.98,
                    "external_job_id": external_id,
                },
            },
            timeout=30,
        )
        print(f"[callback] job={job_id} succeeded -> {response.status_code}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[callback] job={job_id} failed: {exc}", flush=True)


class TrainerHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        job_id = payload.get("job_id")
        token = payload.get("callback_token")
        dataset = payload.get("dataset") or []
        external_id = f"ref-{job_id}"
        print(
            f"[trainer] received job={job_id} method={payload.get('method')} "
            f"dataset_size={len(dataset)}",
            flush=True,
        )
        self._json(
            200,
            {
                "job_id": external_id,
                "status": "accepted",
                "dataset_size": len(dataset),
            },
        )
        if job_id and token:
            threading.Thread(
                target=_callback,
                args=(int(job_id), str(token), external_id),
                daemon=True,
            ).start()

    def log_message(self, fmt: str, *args) -> None:
        print(f"[http] {fmt % args}", flush=True)


if __name__ == "__main__":
    print(
        f"reference trainer on 0.0.0.0:{PORT}, platform={PLATFORM_BASE_URL}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), TrainerHandler).serve_forever()
