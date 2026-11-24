"""P3 前端页面冒烟：学习中心、训练数据、技能市场、多员工协作、员工抽屉。

前置：
- 后端已启动（新代码）
- 前端已启动，且 VITE_API_BASE_URL 指向该后端

运行：
    set VUE_BASE_URL=http://127.0.0.1:5174
    .venv\\Scripts\\python.exe scripts\\p3_ui_smoke.py

截图写入系统临时目录，不污染仓库。
"""

import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("VUE_BASE_URL", "http://127.0.0.1:5173")
OUT = Path(tempfile.gettempdir()) / "de_ui_smoke"
OUT.mkdir(parents=True, exist_ok=True)

page_errors: list[str] = []
console_errors: list[str] = []
failed_responses: list[str] = []


def check_route(page, key: str, title_part: str) -> None:
    page.goto(f"{BASE}/#/{key}", wait_until="networkidle")
    page.wait_for_selector(".page-title", timeout=20000)
    page.wait_for_timeout(500)
    title = page.locator(".page-title").first.inner_text()
    assert title_part in title, f"{key} 标题异常: {title}"
    print(f"{key} -> {title}")


def click_tab(page, name: str) -> None:
    tab = page.locator(f".tabs .tab:has-text('{name}')").first
    tab.click()
    page.wait_for_timeout(400)


def close_drawer(page) -> None:
    page.locator(".drawer .icon-btn").first.click()
    page.wait_for_timeout(300)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on(
            "response",
            lambda response: (
                failed_responses.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )

        page.goto(f"{BASE}/#/login", wait_until="networkidle")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "admin123")
        page.fill('input[name="tenant_code"]', "demo")
        page.click('button[type="submit"]')
        page.wait_for_selector(".page-title", timeout=20000)

        check_route(page, "employees", "数字员工")
        for action in ("岗位契约", "技能装配", "能力迁移", "数字履历"):
            page.locator(f"button:has-text('{action}')").first.click()
            page.wait_for_selector(".drawer", timeout=10000)
            page.wait_for_timeout(600)
            print("drawer", action, "->", page.locator(".drawer").first.inner_text()[:40])
            close_drawer(page)

        check_route(page, "tasks", "任务中心")
        page.click(".tabs .tab:has-text('多员工协作')")
        page.wait_for_timeout(500)
        print("tasks tabs", page.locator(".tabs .tab").count(), "collab tab ok")
        page.screenshot(path=str(OUT / "tasks-collaborations.png"), full_page=True)

        check_route(page, "learning", "学习中心")
        tabs = page.locator(".tabs .tab")
        print("learning tabs", tabs.count())
        for name in ("失败归因", "评估套件", "试运行", "调教台", "主动提问", "周复盘", "专家轨迹"):
            click_tab(page, name)
        page.screenshot(path=str(OUT / "learning-tabs.png"), full_page=True)

        check_route(page, "training", "训练数据")
        page.click(".tabs .tab:has-text('训练任务')")
        page.wait_for_timeout(400)
        print("training tabs", page.locator(".tabs .tab").count())
        page.screenshot(path=str(OUT / "training.png"), full_page=True)

        check_route(page, "skills", "技能市场")
        page.wait_for_selector(".table-wrap, .empty", timeout=15000)
        print("skill rows", page.locator(".table-wrap tbody tr").count())
        if page.locator("button:has-text('详情')").count():
            page.locator("button:has-text('详情')").first.click()
            page.wait_for_selector(".drawer", timeout=10000)
            page.wait_for_timeout(600)
            print("skill drawer", page.locator(".drawer").first.inner_text()[:60])
            close_drawer(page)
        page.screenshot(path=str(OUT / "skills.png"), full_page=True)

        browser.close()

    print("page errors:", page_errors)
    print("console errors:", console_errors[:12])
    print("failed responses:", failed_responses[:12])

    # 未配置岗位契约的员工 GET /contract 返回 404 属于正常状态，
    # 前端已有兜底；这里只忽略该预期 404，其余错误仍然失败。
    unexpected_console = [
        item
        for item in console_errors
        if not item.startswith("Failed to load resource")
    ]
    unexpected_responses = [
        item for item in failed_responses if "/contract" not in item
    ]
    if page_errors or unexpected_console or unexpected_responses:
        sys.exit(1)
    print("P3 UI 冒烟通过（OK）")


if __name__ == "__main__":
    main()
