"""轻量 Prometheus 文本指标，避免额外硬依赖。"""

import re
import threading
import time
from collections import defaultdict

_NUMERIC_SEGMENT = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    return _NUMERIC_SEGMENT.sub("/{id}", path)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._durations: dict[tuple[str, str, str], float] = defaultdict(float)
        self._started_at = time.time()

    def observe_http(
        self, method: str, path: str, status: int, duration_seconds: float
    ) -> None:
        key = (method.upper(), normalize_path(path), str(status))
        with self._lock:
            self._requests[key] += 1
            self._durations[key] += duration_seconds

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = dict(self._durations)
        lines = [
            "# HELP http_requests_total 总请求数",
            "# TYPE http_requests_total counter",
        ]
        for (method, path, status), count in sorted(requests.items()):
            lines.append(
                f'http_requests_total{{method="{_escape(method)}",'
                f'path="{_escape(path)}",status="{_escape(status)}"}} {count}'
            )
        lines += [
            "# HELP http_request_duration_seconds 请求耗时",
            "# TYPE http_request_duration_seconds summary",
        ]
        for (method, path, status), total in sorted(durations.items()):
            labels = (
                f'method="{_escape(method)}",path="{_escape(path)}",'
                f'status="{_escape(status)}"'
            )
            lines.append(f"http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
            lines.append(
                f"http_request_duration_seconds_count{{{labels}}} "
                f"{requests.get((method, path, status), 0)}"
            )
        lines += [
            "# HELP app_uptime_seconds 进程运行时长",
            "# TYPE app_uptime_seconds gauge",
            f"app_uptime_seconds {time.time() - self._started_at:.3f}",
        ]
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
