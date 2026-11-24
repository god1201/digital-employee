export interface NavItem {
  key: string;
  label: string;
  icon: string;
}

export interface NavSection {
  section: string;
  items: NavItem[];
}

export const navSections: NavSection[] = [
  {
    section: "运营",
    items: [
      { key: "dashboard", label: "运行概览", icon: "grid" },
      { key: "tasks", label: "任务中心", icon: "play" },
      { key: "employees", label: "数字员工", icon: "users" },
      { key: "conversations", label: "会话", icon: "spark" },
      { key: "learning", label: "学习中心", icon: "spark" },
      { key: "training", label: "训练数据", icon: "cpu" },
    ],
  },
  {
    section: "组织与团队",
    items: [
      { key: "job-templates", label: "岗位模板", icon: "layers" },
      { key: "team-templates", label: "团队模板", icon: "layers" },
      { key: "teams", label: "我的团队", icon: "users" },
      { key: "projects", label: "项目", icon: "workflow" },
    ],
  },
  {
    section: "知识与风控",
    items: [
      { key: "knowledge", label: "知识库", icon: "book" },
      { key: "multimodal", label: "多模态解析", icon: "layers" },
      { key: "risk", label: "内容风控", icon: "shield" },
      { key: "hallucination", label: "幻觉检测", icon: "search" },
    ],
  },
  {
    section: "业务模块",
    items: [
      { key: "qa", label: "质检", icon: "check" },
      { key: "storyboards", label: "剧本分镜", icon: "film" },
      { key: "aigc", label: "AIGC 生成", icon: "spark" },
      { key: "approvals", label: "审批流", icon: "workflow" },
    ],
  },
  {
    section: "能力接入",
    items: [
      { key: "skills", label: "技能市场", icon: "layers" },
      { key: "tools", label: "工具", icon: "wrench" },
      { key: "mcp", label: "MCP", icon: "plug" },
      { key: "agents", label: "Agent", icon: "cpu" },
      { key: "interfaces", label: "接口登记", icon: "code" },
    ],
  },
  {
    section: "治理",
    items: [
      { key: "access", label: "授权与准入", icon: "key" },
      { key: "alerts", label: "告警", icon: "bell" },
      { key: "audit", label: "审计日志", icon: "list" },
    ],
  },
];
