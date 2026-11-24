"""Vue 前端冒烟测试。

前置：
1. 后端已启动：python -m app.main
2. 前端已启动：cd frontend && npm run dev

运行：
    .venv\\Scripts\\python.exe scripts\\vue_ui_smoke.py
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("VUE_BASE_URL", "http://127.0.0.1:5173")
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)

ROUTES = [
    "dashboard",
    "tasks",
    "employees",
    "team-templates",
    "teams",
    "projects",
    "knowledge",
    "risk",
    "qa",
    "storyboards",
    "aigc",
    "approvals",
    "tools",
    "mcp",
    "agents",
    "interfaces",
    "access",
    "alerts",
    "audit",
]

page_errors: list[str] = []
console_errors: list[str] = []


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )

        page.goto(f"{BASE}/#/login", wait_until="networkidle")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "admin123")
        page.fill('input[name="tenant_code"]', "demo")
        page.click('button[type="submit"]')
        page.wait_for_selector(".page-title", timeout=20000)
        page.wait_for_timeout(700)
        print("dashboard:", page.locator(".page-title").first.inner_text())
        page.screenshot(path=str(OUT / "vue-01-dashboard.png"), full_page=True)

        for key in ROUTES:
            page.goto(f"{BASE}/#/{key}", wait_until="networkidle")
            page.wait_for_selector(".page-title", timeout=15000)
            page.wait_for_timeout(400)
            print(key, "->", page.locator(".page-title").first.inner_text())
            if key in ("tasks", "aigc", "approvals"):
                page.screenshot(path=str(OUT / f"vue-{key}.png"), full_page=True)

        page.goto(f"{BASE}/#/approvals", wait_until="networkidle")
        page.wait_for_selector(".page-title", timeout=15000)
        page.wait_for_timeout(600)
        print("approval tabs:", page.locator(".tabs .tab").count())
        page.click('button:has-text("发起审批")')
        page.wait_for_selector(".modal", timeout=10000)
        page.wait_for_timeout(400)
        print("approval start fields:", page.locator(".modal .field").count())
        page.screenshot(path=str(OUT / "vue-approval-start.png"), full_page=True)
        page.locator(".modal .icon-btn").first.click()

        page.goto(f"{BASE}/#/aigc", wait_until="networkidle")
        page.wait_for_selector(".page-title", timeout=15000)
        page.wait_for_timeout(600)
        print("aigc tabs:", page.locator(".tabs .tab").count())
        page.screenshot(path=str(OUT / "vue-aigc.png"), full_page=True)

        # Agent 使用方反查
        page.goto(f"{BASE}/#/agents", wait_until="networkidle")
        page.wait_for_selector(".page-title", timeout=15000)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "vue-agents.png"), full_page=True)
        usage = page.locator("button.usage-link").first
        print("agent usage:", usage.inner_text())
        usage.click()
        page.wait_for_selector(".drawer .drawer-head", timeout=10000)
        page.wait_for_timeout(500)
        print(
            "agent usage employees:",
            page.locator(".drawer .employee-row").count(),
        )
        page.screenshot(path=str(OUT / "vue-agent-usage.png"), full_page=True)
        page.locator(".drawer .icon-btn").first.click()
        page.wait_for_timeout(300)

        # Agent 创建向导（只走到预览，不提交）
        page.click('button:has-text("新建 Agent")')
        page.wait_for_selector(".agent-wizard", timeout=10000)
        page.fill(
            '.agent-wizard input[placeholder="例如：应收复核 Agent"]',
            "UI 冒烟 Agent",
        )
        page.fill('.agent-wizard input[placeholder="ar_reviewer"]', "ui_smoke_agent")
        page.click('.agent-wizard button:has-text("下一步")')
        page.click('.agent-wizard button:has-text("下一步")')
        tool_cards = page.locator(".agent-wizard .tool-card")
        print("wizard tools:", tool_cards.count())
        if tool_cards.count():
            tool_cards.first.click()
        page.click('.agent-wizard button:has-text("下一步")')
        page.fill('.agent-wizard textarea', "你是冒烟测试 Agent。")
        page.click('.agent-wizard button:has-text("下一步")')
        page.wait_for_timeout(300)
        print(
            "wizard preview blocks:",
            page.locator(".agent-wizard pre.code").count(),
        )
        page.screenshot(path=str(OUT / "vue-agent-wizard.png"), full_page=True)
        page.locator(".agent-wizard .icon-btn").first.click()

        # 项目卡片 / 看板 / 详情抽屉
        page.goto(f"{BASE}/#/projects", wait_until="networkidle")
        page.wait_for_selector(".page-title", timeout=15000)
        page.wait_for_timeout(600)
        project_cards = page.locator(".project-card")
        print("projects:", project_cards.count())
        if project_cards.count():
            project_cards.first.click()
            page.wait_for_selector(".drawer .drawer-head", timeout=10000)
            page.wait_for_timeout(500)
            print(
                "project drawer sections:",
                page.locator(".drawer .section-label").count(),
            )
            page.screenshot(path=str(OUT / "vue-project-detail.png"), full_page=True)
            page.locator(".drawer .drawer-head .icon-btn").click()
            page.wait_for_timeout(300)
        page.locator('.view-toggle button:has-text("看板")').click()
        page.wait_for_timeout(300)
        print("project board columns:", page.locator(".board-column").count())
        page.screenshot(path=str(OUT / "vue-projects-board.png"), full_page=True)

        browser.close()

    print("page errors:", page_errors)
    print("console errors:", console_errors[:12])
    if page_errors or console_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
