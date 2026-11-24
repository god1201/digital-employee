import { createRouter, createWebHashHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/",
    component: () => import("@/components/AppShell.vue"),
    children: [
      { path: "", redirect: "/dashboard" },
      {
        path: "dashboard",
        name: "dashboard",
        component: () => import("@/views/DashboardView.vue"),
        meta: { title: "运行概览" },
      },
      {
        path: "tasks",
        name: "tasks",
        component: () => import("@/views/TasksView.vue"),
        meta: { title: "任务中心" },
      },
      {
        path: "employees",
        name: "employees",
        component: () => import("@/views/EmployeeWorkbenchView.vue"),
        meta: { title: "数字员工" },
      },
      {
        path: "conversations",
        name: "conversations",
        component: () => import("@/views/ConversationsView.vue"),
        meta: { title: "会话" },
      },
      {
        path: "learning",
        name: "learning",
        component: () => import("@/views/LearningView.vue"),
        meta: { title: "学习中心" },
      },
      {
        path: "training",
        name: "training",
        component: () => import("@/views/TrainingView.vue"),
        meta: { title: "训练数据" },
      },
      {
        path: "job-templates",
        name: "job-templates",
        component: () => import("@/views/JobTemplatesView.vue"),
        meta: { title: "岗位模板" },
      },
      {
        path: "team-templates",
        name: "team-templates",
        component: () => import("@/views/TeamTemplatesView.vue"),
        meta: { title: "团队模板" },
      },
      {
        path: "teams",
        name: "teams",
        component: () => import("@/views/TeamsView.vue"),
        meta: { title: "我的团队" },
      },
      {
        path: "projects",
        name: "projects",
        component: () => import("@/views/ProjectsView.vue"),
        meta: { title: "项目" },
      },
      {
        path: "knowledge",
        name: "knowledge",
        component: () => import("@/views/KnowledgeView.vue"),
        meta: { title: "知识库" },
      },
      {
        path: "multimodal",
        name: "multimodal",
        component: () => import("@/views/MultimodalView.vue"),
        meta: { title: "多模态解析" },
      },
      {
        path: "risk",
        name: "risk",
        component: () => import("@/views/RiskView.vue"),
        meta: { title: "内容风控" },
      },
      {
        path: "hallucination",
        name: "hallucination",
        component: () => import("@/views/HallucinationView.vue"),
        meta: { title: "幻觉检测" },
      },
      {
        path: "qa",
        name: "qa",
        component: () => import("@/views/QaView.vue"),
        meta: { title: "质检" },
      },
      {
        path: "storyboards",
        name: "storyboards",
        component: () => import("@/views/StoryboardsView.vue"),
        meta: { title: "AI 剧本分镜" },
      },
      {
        path: "aigc",
        name: "aigc",
        component: () => import("@/views/AigcView.vue"),
        meta: { title: "AIGC 生成" },
      },
      {
        path: "approvals",
        name: "approvals",
        component: () => import("@/views/ApprovalsView.vue"),
        meta: { title: "审批流" },
      },
      {
        path: "skills",
        name: "skills",
        component: () => import("@/views/SkillsView.vue"),
        meta: { title: "技能市场" },
      },
      {
        path: "tools",
        name: "tools",
        component: () => import("@/views/ToolsView.vue"),
        meta: { title: "工具" },
      },
      {
        path: "mcp",
        name: "mcp",
        component: () => import("@/views/McpView.vue"),
        meta: { title: "MCP" },
      },
      {
        path: "agents",
        name: "agents",
        component: () => import("@/views/AgentsView.vue"),
        meta: { title: "Agent" },
      },
      {
        path: "interfaces",
        name: "interfaces",
        component: () => import("@/views/InterfacesView.vue"),
        meta: { title: "接口登记" },
      },
      {
        path: "access",
        name: "access",
        component: () => import("@/views/AccessView.vue"),
        meta: { title: "授权与准入" },
      },
      {
        path: "alerts",
        name: "alerts",
        component: () => import("@/views/AlertsView.vue"),
        meta: { title: "告警" },
      },
      {
        path: "audit",
        name: "audit",
        component: () => import("@/views/AuditView.vue"),
        meta: { title: "审计日志" },
      },
    ],
  },
  { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (!to.meta.public && !auth.token) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.token) {
    return { name: "dashboard" };
  }
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 数字员工` : "数字员工 · 控制台";
});

export default router;
