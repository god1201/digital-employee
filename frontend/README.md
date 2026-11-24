# 数字员工控制台（Vue 3 + Vite + TypeScript）

前后端分离后的独立前端工程。后端只提供 `/api/v1` 与 `/media`，本工程通过 Vite 代理或 `VITE_API_BASE_URL` 访问后端。

## 开发

```bash
cd frontend
npm install
npm run dev
```

默认地址：http://localhost:5173

开发服务器会把以下请求代理到 `http://127.0.0.1:8000`：

- `/api/*`
- `/media/*`

因此本地开发不需要改后端 CORS。

## 构建

```bash
npm run build
npm run preview
```

产物输出到 `frontend/dist/`。

## 环境变量

复制 `.env.example` 为 `.env.local`：

```env
VITE_API_BASE_URL=/api/v1
```

- 同域部署（Nginx 反代 `/api`）保持 `/api/v1`。
- 前后端不同域名时改为完整地址，例如 `https://api.example.com/api/v1`。
- 同时需要把前端地址加入后端 `CORS_ORIGINS`。

## 生产部署示例（Nginx）

```nginx
server {
    listen 80;
    server_name console.example.com;

    root /srv/digital-employee/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

## 页面

- 运行概览、任务中心、数字员工
- 团队模板、我的团队
- 知识库、内容风控、质检、剧本分镜、AIGC 生成、审批流
- 工具、MCP、Agent、接口登记
- 授权与准入、告警、审计日志

## 技术栈

- Vue 3 `<script setup lang="ts">`
- Vue Router（Hash 路由）
- Pinia
- Vite
- 原生 CSS（沿用原控制台视觉）

## 冒烟

后端与前端都启动后，在项目根目录执行：

```bash
.venv\Scripts\python.exe scripts\vue_ui_smoke.py
```
