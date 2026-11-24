"""真实 DPO/SFT trainer（小模型参考实现）。

与 `trainer_reference.py` 使用同一 HTTP 契约，但会真正执行梯度训练：
- 接收平台派发的 preference pairs / dataset
- 加载可配置的因果语言模型（默认 `uer/gpt2-chinese-cluecorpussmall`）
- `method=dpo`：DPO 偏好损失；`method=sft`：chosen 文本交叉熵
- 保存模型到 `data/training/models/<job_id>`
- 通过 `X-Training-Token` 回调 running/succeeded/failed

运行：
    .venv-trainer\\Scripts\\python.exe scripts\\trainer_dpo.py

环境变量：
    TRAINER_PORT=9101
    PLATFORM_BASE_URL=http://127.0.0.1:8000
    TRAINER_MODEL=uer/gpt2-chinese-cluecorpussmall
    TRAINER_DEVICE=auto|cpu|cuda
    TRAINER_MAX_STEPS=2
    TRAINER_MAX_LENGTH=128
    TRAINER_LR=5e-5
    TRAINER_BETA=0.1
    TRAINER_OUTPUT_DIR=data/training/models
    HF_ENDPOINT=https://hf-mirror.com
"""

import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import httpx  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.getenv("TRAINER_PORT", "9101"))
MODEL_NAME = os.getenv("TRAINER_MODEL", "uer/gpt2-chinese-cluecorpussmall")
DEVICE = os.getenv("TRAINER_DEVICE", "auto")
MAX_STEPS = max(1, int(os.getenv("TRAINER_MAX_STEPS", "2")))
MAX_LENGTH = max(32, int(os.getenv("TRAINER_MAX_LENGTH", "128")))
LR = float(os.getenv("TRAINER_LR", "5e-5"))
BETA = float(os.getenv("TRAINER_BETA", "0.1"))
OUTPUT_DIR = Path(os.getenv("TRAINER_OUTPUT_DIR", "data/training/models"))


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return _text(parsed)
    if isinstance(value, dict):
        for key in ("text", "content", "answer", "summary", "exact"):
            if value.get(key):
                return str(value[key])
        if value.get("keywords"):
            return "、".join(str(item) for item in value["keywords"])
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _encode_pair(tokenizer, prompt: str, response: str) -> dict:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"] if prompt else []
    response_ids = tokenizer(response, add_special_tokens=False)["input_ids"]
    if not response_ids:
        response_ids = [tokenizer.pad_token_id or 0]
    ids = (prompt_ids + response_ids)[:MAX_LENGTH]
    response_mask = [0] * len(prompt_ids) + [1] * len(response_ids)
    response_mask = response_mask[: len(ids)]
    return {
        "input_ids": torch.tensor([ids], dtype=torch.long),
        "attention_mask": torch.ones(1, len(ids), dtype=torch.long),
        "response_mask": torch.tensor([response_mask], dtype=torch.long),
    }


def _response_logprob(model, batch: dict) -> torch.Tensor:
    outputs = model(
        input_ids=batch["input_ids"],
        attention_mask=batch["attention_mask"],
    )
    logits = outputs.logits[:, :-1, :]
    labels = batch["input_ids"][:, 1:]
    log_probs = torch.log_softmax(logits, dim=-1)
    token_log_probs = log_probs.gather(-1, labels.unsqueeze(-1)).squeeze(-1)
    mask = batch["response_mask"][:, 1:].to(token_log_probs.dtype)
    return (token_log_probs * mask).sum(dim=-1)


def _sft_loss(model, batch: dict) -> torch.Tensor:
    outputs = model(
        input_ids=batch["input_ids"],
        attention_mask=batch["attention_mask"],
    )
    logits = outputs.logits[:, :-1, :]
    labels = batch["input_ids"][:, 1:].clone()
    labels[batch["response_mask"][:, 1:] == 0] = -100
    return F.cross_entropy(
        logits.reshape(-1, logits.size(-1)),
        labels.reshape(-1),
        ignore_index=-100,
    )


def _callback(job_id: int, token: str, payload: dict) -> None:
    url = f"{PLATFORM_BASE_URL}/api/v1/training-jobs/{job_id}/status"
    try:
        response = httpx.post(
            url,
            headers={"X-Training-Token": token},
            json=payload,
            timeout=30,
        )
        print(
            f"[callback] job={job_id} {payload.get('status')} -> "
            f"{response.status_code}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[callback] job={job_id} failed: {exc}", flush=True)


def _train(job_id: int, token: str, method: str, dataset: list[dict]) -> None:
    started = time.time()
    try:
        _callback(job_id, token, {"status": "running", "metrics": {"model": MODEL_NAME}})
        device = torch.device(
            "cuda"
            if DEVICE == "auto" and torch.cuda.is_available()
            else "cuda"
            if DEVICE == "cuda" and torch.cuda.is_available()
            else "cpu"
        )
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForCausalLM.from_pretrained(MODEL_NAME).to(device)
        pad_id = tokenizer.pad_token_id
        if pad_id is None:
            pad_id = 0
            tokenizer.pad_token_id = pad_id
        eos_id = tokenizer.eos_token_id
        if eos_id is None or eos_id >= len(tokenizer):
            eos_id = pad_id
        model.config.pad_token_id = pad_id
        model.config.eos_token_id = eos_id
        model.config.bos_token_id = eos_id
        model.train()

        reference = None
        if method == "dpo":
            reference = AutoModelForCausalLM.from_pretrained(MODEL_NAME).to(device)
            reference.eval()
            for param in reference.parameters():
                param.requires_grad_(False)

        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=LR
        )
        samples = []
        for item in dataset:
            prompt = _text(item.get("prompt"))
            chosen = _text(item.get("chosen") or item.get("response"))
            rejected = _text(item.get("rejected"))
            if not chosen:
                continue
            samples.append((prompt, chosen, rejected))
        if not samples:
            raise ValueError("数据集没有可用的 chosen 文本")

        losses: list[float] = []
        preferred = 0
        for step in range(MAX_STEPS):
            prompt, chosen, rejected = samples[step % len(samples)]
            chosen_batch = _encode_pair(tokenizer, prompt, chosen)
            optimizer.zero_grad(set_to_none=True)
            if method == "sft" or not rejected:
                loss = _sft_loss(model, chosen_batch)
            else:
                rejected_batch = _encode_pair(tokenizer, prompt, rejected)
                chosen_logp = _response_logprob(model, chosen_batch)
                rejected_logp = _response_logprob(model, rejected_batch)
                with torch.no_grad():
                    ref_chosen = _response_logprob(reference, chosen_batch)
                    ref_rejected = _response_logprob(reference, rejected_batch)
                margin = (chosen_logp - ref_chosen) - (rejected_logp - ref_rejected)
                loss = -F.logsigmoid(BETA * margin).mean()
                preferred += int(margin.item() > 0)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
            print(
                f"[train] job={job_id} step={step + 1}/{MAX_STEPS} "
                f"loss={losses[-1]:.4f}",
                flush=True,
            )

        output_dir = OUTPUT_DIR / str(job_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)
        metrics = {
            "loss": round(sum(losses) / len(losses), 6),
            "steps": len(losses),
            "model": MODEL_NAME,
            "device": str(device),
            "method": method,
            "output_dir": str(output_dir),
            "elapsed_seconds": round(time.time() - started, 3),
        }
        if method == "dpo":
            metrics["preference_accuracy"] = round(preferred / len(losses), 4)
        _callback(job_id, token, {"status": "succeeded", "metrics": metrics})
    except Exception as exc:  # noqa: BLE001
        print(f"[train] job={job_id} failed: {exc}", flush=True)
        traceback.print_exc()
        _callback(
            job_id,
            token,
            {"status": "failed", "error": str(exc)[:2000], "metrics": {}},
        )


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
            self._json(200, {"status": "ok", "trainer": "dpo", "model": MODEL_NAME})
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
        method = str(payload.get("method") or "dpo").lower()
        print(
            f"[trainer] received job={job_id} method={method} "
            f"dataset_size={len(dataset)}",
            flush=True,
        )
        self._json(
            200,
            {
                "job_id": f"dpo-{job_id}",
                "status": "accepted",
                "dataset_size": len(dataset),
            },
        )
        if job_id and token:
            threading.Thread(
                target=_train,
                args=(int(job_id), str(token), method, dataset),
                daemon=True,
            ).start()

    def log_message(self, fmt: str, *args) -> None:
        print(f"[http] {fmt % args}", flush=True)


if __name__ == "__main__":
    print(
        f"DPO/SFT trainer on 0.0.0.0:{PORT}, model={MODEL_NAME}, "
        f"device={DEVICE}, platform={PLATFORM_BASE_URL}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), TrainerHandler).serve_forever()
