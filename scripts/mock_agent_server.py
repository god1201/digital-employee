"""本地 Mock 第三方 Agent，用于冒烟测试。

POST 任意路径，回显请求体：
    {"output": {"received": <body>, "agent": "mock"}, "tokens": 11}
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            data = {"raw": raw.decode("utf-8", errors="replace")}

        payload = {"output": {"received": data, "agent": "mock"}, "tokens": 11}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8020
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
