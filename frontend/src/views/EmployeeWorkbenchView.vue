<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AgentPickerModal from "@/components/AgentPickerModal.vue";
import AppIcon from "@/components/AppIcon.vue";
import CapabilityMigrationDrawer from "@/components/CapabilityMigrationDrawer.vue";
import ChatDrawer from "@/components/ChatDrawer.vue";
import ChatPanel from "@/components/ChatPanel.vue";
import EmployeeContractDrawer from "@/components/EmployeeContractDrawer.vue";
import EmployeeCreateModal from "@/components/EmployeeCreateModal.vue";
import EmployeeOnboardingDrawer from "@/components/EmployeeOnboardingDrawer.vue";
import EmployeePersonaDrawer from "@/components/EmployeePersonaDrawer.vue";
import EmployeeProfileDrawer from "@/components/EmployeeProfileDrawer.vue";
import EmployeeSkillsDrawer from "@/components/EmployeeSkillsDrawer.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProjectPickerModal from "@/components/ProjectPickerModal.vue";
import RadarChart from "@/components/RadarChart.vue";
import StatusPill from "@/components/StatusPill.vue";
import TaskDetailDrawer from "@/components/TaskDetailDrawer.vue";
import TaskLinkModal from "@/components/TaskLinkModal.vue";
import TokenUsagePanel from "@/components/TokenUsagePanel.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useEmployeeStore } from "@/stores/employee";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
  position?: string | null;
  status: string;
  agent_id?: number | null;
  agent_name?: string | null;
  model_name?: string;
  created_at: string;
}

const route = useRoute();
const router = useRouter();
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();
const employeeStore = useEmployeeStore();

const rows = ref<Employee[]>([]);
const agents = ref<any[]>([]);
const selected = ref<Employee | null>(null);
const workbench = ref<any>(null);
const profile = ref<any>(null);
const loading = ref(false);
const detailLoading = ref(false);
const keyword = ref("");
const showInactive = ref(false);
const tab = ref<"overview" | "work" | "projects" | "tokens" | "config">(
  "overview",
);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return rows.value;
  return rows.value.filter((employee) =>
    [
      employee.name,
      employee.code,
      employee.position,
      employee.agent_name,
    ]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

const agentMap = computed(() => {
  const map: Record<number, any> = {};
  for (const agent of agents.value) map[agent.id] = agent;
  return map;
});

const statusLabel = computed(() => {
  const value = workbench.value?.status;
  if (value === "working") return "工作中";
  if (value === "waiting") return "等待确认";
  if (value === "offline") return "已停用";
  return "空闲";
});

const summary = computed(() => workbench.value?.token_summary || {});
const recentTasks = computed(() => workbench.value?.recent_tasks || []);
const projects = computed(() => workbench.value?.projects || []);
const currentTask = computed(() => workbench.value?.current_task || null);
const selectedAgent = computed(
  () => workbench.value?.agent || agentMap.value[selected.value?.agent_id || 0],
);

function agentName(employee: Employee): string {
  return (
    employee.agent_name ||
    agentMap.value[employee.agent_id || 0]?.name ||
    "未绑定 Agent"
  );
}

async function loadDetail(): Promise<void> {
  if (!selected.value) return;
  detailLoading.value = true;
  try {
    const [wb, prof] = await Promise.all([
      api.get<any>(`/digital-employees/${selected.value.id}/workbench`),
      api
        .get<any>(`/digital-employees/${selected.value.id}/profile`)
        .catch(() => null),
    ]);
    workbench.value = wb;
    profile.value = prof;
    employeeStore.updateSummary(wb);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载工作台失败", "error");
  } finally {
    detailLoading.value = false;
  }
}

async function selectEmployee(employee: Employee): Promise<void> {
  selected.value = employee;
  employeeStore.select(employee);
  workbench.value = null;
  profile.value = null;
  tab.value = "overview";
  if (String(route.query.employee || "") !== String(employee.id)) {
    router.replace({ query: { ...route.query, employee: String(employee.id) } });
  }
  await loadDetail();
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const queryId = Number(route.query.employee);
    const statusQuery = showInactive.value ? "" : "&status=active";
    const [employeeData, agentData] = await Promise.all([
      api.get<Paged<Employee>>(
        `/digital-employees?page_size=200${statusQuery}`,
      ),
      api.get<Paged<any>>("/agents?page_size=200&status=active"),
    ]);
    let employees = employeeData.items;
    // 深链接到已停用员工（如从 Agent 使用方抽屉跳转）时自动放开过滤，
    // 否则会被回退到第一个在岗员工。
    if (
      queryId &&
      !showInactive.value &&
      !employees.some((item) => item.id === queryId)
    ) {
      showInactive.value = true;
      const allEmployees = await api.get<Paged<Employee>>(
        "/digital-employees?page_size=200",
      );
      employees = allEmployees.items;
    }
    rows.value = employees;
    agents.value = agentData.items;
    const target =
      rows.value.find((item) => item.id === queryId) ||
      rows.value.find((item) => item.id === selected.value?.id) ||
      rows.value[0];
    if (target) {
      await selectEmployee(target);
    } else {
      selected.value = null;
      employeeStore.clear();
    }
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载员工失败", "error");
  } finally {
    loading.value = false;
  }
}

function toggleInactive(): void {
  showInactive.value = !showInactive.value;
  void load();
}

function createEmployee(): void {
  modal.openCustom(EmployeeCreateModal, {
    agents: agents.value,
    onCreated: async (employee: Employee) => {
      toast.push("数字员工已创建");
      await load();
      const row = rows.value.find((item) => item.id === employee.id);
      if (row) await selectEmployee(row);
    },
  });
}

function bindAgent(): void {
  if (!selected.value) return;
  modal.openCustom(AgentPickerModal, {
    agents: agents.value,
    currentId: selected.value.agent_id,
    onSelect: async (agent: any) => {
      try {
        await api.patch(`/digital-employees/${selected.value?.id}`, {
          agent_id: agent.id,
        });
        toast.push(`已绑定 Agent：${agent.name}`);
        await load();
        await loadDetail();
      } catch (err) {
        toast.push(err instanceof Error ? err.message : "绑定失败", "error");
      }
    },
  });
}

function editEmployee(): void {
  if (!selected.value) return;
  const current = selected.value;
  const detail = workbench.value?.employee || {};
  modal.openForm({
    title: "编辑员工资料",
    sub: "Agent 负责能力，员工负责岗位身份与契约。",
    fields: [
      { name: "name", label: "姓名", value: current.name, required: true },
      { name: "position", label: "岗位", value: current.position || "" },
      {
        name: "description",
        label: "职责描述",
        type: "textarea",
        rows: 3,
        value: detail.description || "",
      },
      {
        name: "system_prompt",
        label: "员工级提示词",
        type: "textarea",
        rows: 4,
        value: detail.system_prompt || "",
      },
    ],
    submitLabel: "保存",
    onSubmit: async (values) => {
      await api.patch(`/digital-employees/${current.id}`, values);
      toast.push("资料已更新");
      await load();
      await loadDetail();
    },
  });
}

function openConfig(
  component: any,
  extra: Record<string, unknown> = {},
): void {
  if (!selected.value) return;
  drawer.open(component, {
    employee: selected.value,
    onChanged: async () => {
      await load();
      await loadDetail();
    },
    ...extra,
  });
}

function openChat(): void {
  if (!selected.value) return;
  drawer.open(ChatDrawer, { employee: selected.value });
}

function openTask(id: number): void {
  drawer.open(TaskDetailDrawer, {
    id,
    employeeName: selected.value?.name,
    onChanged: loadDetail,
  });
}

function createProject(): void {
  if (!selected.value) return;
  modal.openForm({
    title: "新建项目",
    sub: "项目用于归集任务、会话与 Token 成本。",
    fields: [
      { name: "name", label: "项目名称", required: true },
      { name: "code", label: "编码", required: true },
      { name: "description", label: "描述", type: "textarea", rows: 3 },
    ],
    submitLabel: "创建项目",
    onSubmit: async (values) => {
      await api.post("/projects", {
        name: values.name,
        code: values.code,
        description: values.description || "",
        status: "active",
        owner_employee_id: selected.value?.id,
      });
      toast.push("项目已创建");
      await loadDetail();
    },
  });
}

async function joinProject(): Promise<void> {
  if (!selected.value) return;
  const employeeId = selected.value.id;
  try {
    const allProjects = await api.get<any[]>("/projects");
    const joinedIds = projects.value
      .filter((project: any) => project.role !== "task_member")
      .map((project: any) => project.id);
    modal.openCustom(ProjectPickerModal, {
      projects: allProjects,
      excludeIds: joinedIds,
      onSelect: async (project: any) => {
        try {
          await api.post(`/projects/${project.id}/members`, {
            employee_id: employeeId,
            role: "member",
          });
          toast.push(`已加入项目：${project.name}`);
          await loadDetail();
        } catch (err) {
          toast.push(err instanceof Error ? err.message : "加入项目失败", "error");
        }
      },
    });
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载项目失败", "error");
  }
}

function openProjectWorkspace(project: any): void {
  void router.push({ name: "projects", query: { project: String(project.id) } });
}

function linkTaskToProject(project: any): void {
  if (!selected.value) return;
  modal.openCustom(TaskLinkModal, {
    projectId: project.id,
    projectName: project.name,
    employeeId: selected.value.id,
    onLinked: loadDetail,
  });
}

function tokenText(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value ?? 0);
}

function projectRoleLabel(role: string): string {
  if (role === "owner") return "负责人";
  if (role === "reviewer") return "评审";
  if (role === "task_member") return "任务参与";
  return "成员";
}

function projectStatusLabel(status: string): string {
  if (status === "active") return "进行中";
  if (status === "paused") return "已暂停";
  if (status === "archived") return "已归档";
  return status;
}

watch(
  () => route.query.employee,
  async (value) => {
    const id = Number(value);
    if (!id || selected.value?.id === id) return;
    const row = rows.value.find((item) => item.id === id);
    if (row) {
      await selectEmployee(row);
      return;
    }
    // 目标员工可能已停用（例如从 Agent 使用方抽屉跳转）：放开过滤后重新加载。
    if (!showInactive.value) {
      showInactive.value = true;
      await load();
    }
  },
);

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="workforce / workbench"
    title="数字员工"
    sub="选择员工进入工作台：状态、工作、项目、Token 与对话。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load">
        <AppIcon name="refresh" />刷新
      </button>
      <button class="btn btn-primary" @click="createEmployee">
        <AppIcon name="plus" />新增员工
      </button>
    </template>
  </PageHeader>

  <div class="workbench-layout">
    <aside class="roster">
      <div class="roster-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索姓名、岗位、Agent" />
      </div>
      <div class="roster-filter">
        <span class="muted">
          {{ filtered.length }} 位{{ showInactive ? "员工" : "在职员工" }}
        </span>
        <button type="button" class="roster-toggle" @click="toggleInactive">
          {{ showInactive ? "隐藏停用" : "显示停用" }}
        </button>
      </div>
      <div class="roster-list">
        <div v-if="loading" class="muted roster-empty">加载员工…</div>
        <div v-else-if="!filtered.length" class="roster-empty">
          <b>还没有数字员工</b>
          <p class="muted">先创建 Agent，再创建数字员工。</p>
          <button class="btn btn-sm btn-primary" @click="createEmployee">
            新增员工
          </button>
        </div>
        <button
          v-for="employee in filtered"
          :key="employee.id"
          type="button"
          class="roster-item"
          :class="{ active: selected?.id === employee.id }"
          @click="selectEmployee(employee)"
        >
          <span class="roster-avatar">{{ (employee.name || "E").slice(0, 1) }}</span>
          <span class="roster-meta">
            <b>{{ employee.name }}</b>
            <small>{{ employee.position || "未设置岗位" }}</small>
            <small class="agent-line">{{ agentName(employee) }}</small>
          </span>
          <span class="roster-status" :class="employee.status">
            {{ employee.status }}
          </span>
        </button>
      </div>
    </aside>

    <section class="workbench-main">
      <div v-if="!selected" class="panel wb-empty">
        <AppIcon name="users" />
        <b>选择一个数字员工</b>
        <p class="muted">查看状态、工作、项目与 Token，或直接开始对话。</p>
      </div>

      <template v-else>
        <div class="employee-head panel">
          <span class="head-avatar">{{ (selected.name || "E").slice(0, 1) }}</span>
          <div class="head-main">
            <div class="head-title">
              <h2>{{ selected.name }}</h2>
              <StatusPill :status="workbench?.status || selected.status" />
              <span class="head-status">{{ statusLabel }}</span>
            </div>
            <p class="muted">
              {{ selected.position || "未设置岗位" }} ·
              {{ selected.code }} ·
              Agent：{{ selectedAgent?.name || "未绑定" }}
            </p>
          </div>
          <div class="head-actions">
            <button class="btn btn-sm btn-primary" @click="openChat">
              <AppIcon name="spark" />去对话
            </button>
            <button class="btn btn-sm btn-ghost" @click="editEmployee">编辑资料</button>
          </div>
        </div>

        <div class="tabs wb-tabs">
          <button class="tab" :class="{ active: tab === 'overview' }" @click="tab = 'overview'">
            概览
          </button>
          <button class="tab" :class="{ active: tab === 'work' }" @click="tab = 'work'">
            工作
          </button>
          <button class="tab" :class="{ active: tab === 'projects' }" @click="tab = 'projects'">
            项目
          </button>
          <button class="tab" :class="{ active: tab === 'tokens' }" @click="tab = 'tokens'">
            Token
          </button>
          <button class="tab" :class="{ active: tab === 'config' }" @click="tab = 'config'">
            配置
          </button>
        </div>

        <div v-if="detailLoading" class="panel muted wb-loading">加载工作台…</div>

        <template v-else>
          <div v-if="tab === 'overview'" class="tab-body">
            <div class="metric-row">
              <div class="metric-card">
                <span>当前状态</span>
                <b>{{ statusLabel }}</b>
                <small class="muted">{{ currentTask ? "有进行中的任务" : "可接受新指令" }}</small>
              </div>
              <div class="metric-card">
                <span>今日 Token</span>
                <b class="mono">{{ tokenText(summary.today || 0) }}</b>
                <small class="muted">任务 + 对话</small>
              </div>
              <div class="metric-card">
                <span>近 7 天 Token</span>
                <b class="mono">{{ tokenText(summary["7d"] || 0) }}</b>
                <small class="muted">成本 {{ Number(summary.cost_7d || 0).toFixed(4) }}</small>
              </div>
              <div class="metric-card">
                <span>参与项目</span>
                <b class="mono">{{ projects.length }}</b>
                <small class="muted">含任务关联项目</small>
              </div>
            </div>

            <div class="overview-grid">
              <div class="panel sub-panel">
                <div class="sub-head">
                  <b>当前工作</b>
                  <span class="muted">最近 10 条任务</span>
                </div>
                <div v-if="currentTask" class="current-task">
                  <span class="live-dot" />
                  <div>
                    <b>{{ currentTask.title }}</b>
                    <small class="muted">{{ currentTask.status }} · #{{ currentTask.id }}</small>
                  </div>
                  <button class="btn btn-sm btn-ghost" @click="openTask(currentTask.id)">详情</button>
                </div>
                <div v-else class="muted empty-line">暂无进行中的任务</div>
                <div class="task-mini-list">
                  <button
                    v-for="task in recentTasks.slice(0, 5)"
                    :key="task.id"
                    type="button"
                    class="task-mini"
                    @click="openTask(task.id)"
                  >
                    <span>
                      <b>{{ task.title }}</b>
                      <small class="muted">{{ fmtDate(task.created_at) }}</small>
                    </span>
                    <StatusPill :status="task.status" />
                    <span class="mono">{{ tokenText(task.tokens) }}</span>
                  </button>
                </div>
              </div>

              <div class="panel sub-panel">
                <div class="sub-head">
                  <b>绑定 Agent</b>
                  <button class="btn btn-sm btn-ghost" @click="bindAgent">更换</button>
                </div>
                <div v-if="selectedAgent" class="agent-view">
                  <div class="agent-view-top">
                    <span class="agent-mark">{{ (selectedAgent.name || "A").slice(0, 1) }}</span>
                    <div>
                      <b>{{ selectedAgent.name }}</b>
                      <small class="mono">{{ selectedAgent.code }}</small>
                    </div>
                  </div>
                  <div class="agent-tags">
                    <span class="tag">{{ selectedAgent.model_name || "默认模型" }}</span>
                    <span class="tag">{{ (selectedAgent.tools || []).length }} 个工具</span>
                    <span class="tag">{{ (selectedAgent.capabilities || []).length }} 项能力</span>
                  </div>
                  <p v-if="selectedAgent.capabilities?.length" class="muted agent-caps">
                    {{ (selectedAgent.capabilities || []).join(" · ") }}
                  </p>
                </div>
                <div v-else class="muted empty-line">
                  未绑定 Agent。绑定后可复用其模型、工具与能力。
                  <button class="btn btn-sm btn-primary" @click="bindAgent">立即绑定</button>
                </div>
              </div>

              <div class="panel sub-panel radar-panel">
                <div class="sub-head">
                  <b>能力雷达</b>
                  <span class="muted">数字履历</span>
                </div>
                <RadarChart
                  v-if="profile?.capability_radar?.length"
                  :axes="profile.capability_radar"
                  :size="280"
                />
                <div v-else class="muted empty-line">暂无足够数据绘制雷达图。</div>
              </div>
            </div>

            <div class="panel sub-panel">
              <div class="sub-head">
                <b>参与项目</b>
                <button class="btn btn-sm btn-ghost" @click="tab = 'projects'">查看全部</button>
              </div>
              <div v-if="projects.length" class="project-chips">
                <button
                  v-for="project in projects.slice(0, 6)"
                  :key="project.id"
                  type="button"
                  class="project-chip"
                  @click="tab = 'projects'"
                >
                  <b>{{ project.name }}</b>
                  <small>{{ projectRoleLabel(project.role) }} · {{ projectStatusLabel(project.status) }}</small>
                </button>
              </div>
              <div v-else class="muted empty-line">还没有参与项目</div>
            </div>
          </div>

          <div v-else-if="tab === 'work'" class="tab-body">
            <div class="panel sub-panel">
              <div class="sub-head">
                <b>最近工作</b>
                <span class="muted">任务、Token 与项目</span>
              </div>
              <div v-if="recentTasks.length" class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>任务</th>
                      <th>状态</th>
                      <th>类型</th>
                      <th>Token</th>
                      <th>项目</th>
                      <th>创建</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="task in recentTasks" :key="task.id">
                      <td>
                        <b>{{ task.title }}</b>
                        <small class="muted mono"> #{{ task.id }}</small>
                      </td>
                      <td><StatusPill :status="task.status" /></td>
                      <td class="mono">{{ task.task_type }}</td>
                      <td class="mono">{{ task.tokens }}</td>
                      <td>{{ task.project_id ? `#${task.project_id}` : "—" }}</td>
                      <td class="muted">{{ fmtDate(task.created_at) }}</td>
                      <td>
                        <button class="btn btn-sm" @click="openTask(task.id)">详情</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="muted empty-line">还没有工作记录</div>
            </div>
          </div>

          <div v-else-if="tab === 'projects'" class="tab-body">
            <div class="sub-head projects-head">
              <b>参与项目</b>
              <div class="head-buttons">
                <button class="btn btn-sm" @click="joinProject">
                  <AppIcon name="plus" />加入项目
                </button>
                <button class="btn btn-sm btn-primary" @click="createProject">
                  <AppIcon name="plus" />新建项目
                </button>
              </div>
            </div>
            <div v-if="projects.length" class="project-grid">
              <div v-for="project in projects" :key="project.id" class="project-card">
                <div class="project-card-head">
                  <b>{{ project.name }}</b>
                  <span class="tag">{{ projectRoleLabel(project.role) }}</span>
                </div>
                <small class="mono muted">{{ project.code }}</small>
                <div class="project-stats">
                  <span>状态 · {{ projectStatusLabel(project.status) }}</span>
                  <span>Token · {{ tokenText(project.token_usage?.tokens || 0) }}</span>
                  <span>成本 · {{ Number(project.token_usage?.cost || 0).toFixed(4) }}</span>
                </div>
                <div class="project-actions">
                  <button class="btn btn-sm btn-ghost" @click="openProjectWorkspace(project)">
                    打开项目
                  </button>
                  <button class="btn btn-sm" @click="linkTaskToProject(project)">
                    关联任务
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="panel muted wb-empty">
              还没有项目。创建项目后可以把任务与会话归集到同一业务目标。
            </div>
          </div>

          <div v-else-if="tab === 'tokens'" class="tab-body">
            <TokenUsagePanel :employee-id="selected.id" />
          </div>

          <div v-else class="tab-body">
            <div class="config-grid">
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="cpu" /></span>
                  <div>
                    <b>Agent 绑定</b>
                    <small class="muted">复用模型、工具与能力</small>
                  </div>
                </div>
                <p class="muted">
                  {{ selectedAgent?.name || "未绑定 Agent" }}
                </p>
                <button class="btn btn-sm" @click="bindAgent">
                  {{ selectedAgent ? "更换 Agent" : "绑定 Agent" }}
                </button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="shield" /></span>
                  <div>
                    <b>岗位契约</b>
                    <small class="muted">can_do / cannot_do / must_ask / 自主权</small>
                  </div>
                </div>
                <p class="muted">红线决定对话中的工具是否允许执行。</p>
                <button class="btn btn-sm" @click="openConfig(EmployeeContractDrawer)">管理契约</button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="spark" /></span>
                  <div>
                    <b>人格风格</b>
                    <small class="muted">称呼、语气、格式与禁忌词</small>
                  </div>
                </div>
                <p class="muted">技能只输出结构化结果，人格层统一润色。</p>
                <button class="btn btn-sm" @click="openConfig(EmployeePersonaDrawer)">编辑人格</button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="layers" /></span>
                  <div>
                    <b>技能装配</b>
                    <small class="muted">技能、依赖、冲突与权限并集</small>
                  </div>
                </div>
                <p class="muted">对话会加载员工已启用技能提供的工具。</p>
                <button class="btn btn-sm" @click="openConfig(EmployeeSkillsDrawer)">管理技能</button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="book" /></span>
                  <div>
                    <b>入职引导</b>
                    <small class="muted">JD/SOP、示范案例与导师确认</small>
                  </div>
                </div>
                <p class="muted">把岗位文档转成契约草稿与 Few-shot 案例。</p>
                <button class="btn btn-sm" @click="openConfig(EmployeeOnboardingDrawer)">开始入职</button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="workflow" /></span>
                  <div>
                    <b>能力迁移</b>
                    <small class="muted">技能、工件、偏好与契约草稿</small>
                  </div>
                </div>
                <p class="muted">从其他员工复制可复用能力，保留冲突告警。</p>
                <button class="btn btn-sm" @click="openConfig(CapabilityMigrationDrawer)">迁移能力</button>
              </div>
              <div class="config-card">
                <div class="config-head">
                  <span class="config-icon"><AppIcon name="list" /></span>
                  <div>
                    <b>数字履历</b>
                    <small class="muted">接管率、一次通过、学习曲线</small>
                  </div>
                </div>
                <p class="muted">查看能力雷达、试运行与学习工件。</p>
                <button class="btn btn-sm" @click="openConfig(EmployeeProfileDrawer)">查看履历</button>
              </div>
            </div>
          </div>
        </template>
      </template>
    </section>

    <aside v-if="selected" class="workbench-chat">
      <ChatPanel :key="selected.id" :employee-id="selected.id" @updated="loadDetail" />
    </aside>
  </div>
</template>

<style scoped>
.workbench-layout {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr) 370px;
  gap: 12px;
  align-items: start;
}
.roster {
  border: 1px solid var(--line);
  border-radius: 13px;
  background: var(--panel);
  padding: 9px;
  position: sticky;
  top: 12px;
  max-height: calc(100vh - 130px);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.roster-search {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--panel-2);
  padding: 0 9px;
  height: 32px;
}
.roster-search :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--dim);
}
.roster-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 11.5px;
}
.roster-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0 2px;
}
.roster-filter .muted {
  font-size: 10px;
}
.roster-toggle {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--dim);
  border-radius: 999px;
  font-size: 9.5px;
  padding: 2px 7px;
  cursor: pointer;
}
.roster-toggle:hover {
  border-color: var(--line-strong);
  color: var(--text);
}
.roster-list {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.roster-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  text-align: left;
  padding: 8px;
  cursor: pointer;
}
.roster-item:hover {
  background: var(--panel-2);
}
.roster-item.active {
  border-color: color-mix(in srgb, var(--amber) 38%, var(--line));
  background: rgba(232, 163, 61, 0.07);
}
.roster-avatar,
.head-avatar {
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.15);
  color: var(--amber);
  font-weight: 700;
}
.roster-avatar {
  width: 28px;
  height: 28px;
  font-size: 11px;
  flex: 0 0 auto;
}
.roster-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.roster-meta b {
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.roster-meta small {
  font-size: 9.5px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.agent-line {
  color: color-mix(in srgb, var(--amber) 65%, var(--dim)) !important;
}
.roster-status {
  font-size: 8.5px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 5px;
}
.roster-status.active {
  color: #4fd1b0;
  border-color: rgba(79, 209, 176, 0.35);
}
.roster-status.disabled,
.roster-status.draft {
  color: var(--dim);
}
.roster-empty {
  padding: 18px 8px;
  text-align: center;
  font-size: 11px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  align-items: center;
}
.workbench-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.employee-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
}
.head-avatar {
  width: 46px;
  height: 46px;
  font-size: 17px;
  flex: 0 0 auto;
}
.head-main {
  min-width: 0;
  flex: 1;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.head-title h2 {
  margin: 0;
  font-size: 18px;
}
.head-status {
  font-size: 10px;
  color: var(--dim);
}
.head-main p {
  margin: 4px 0 0;
  font-size: 11px;
}
.head-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.wb-tabs {
  margin-bottom: 0;
}
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
}
.metric-card {
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel);
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.metric-card span {
  font-size: 10.5px;
  color: var(--dim);
}
.metric-card b {
  font-size: 17px;
}
.metric-card small {
  font-size: 10px;
}
.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
}
.sub-panel {
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}
.sub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 9px;
}
.sub-head b {
  font-size: 12.5px;
}
.sub-head .muted {
  font-size: 10px;
}
.current-task {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid color-mix(in srgb, var(--amber) 30%, var(--line));
  border-radius: 9px;
  padding: 8px 9px;
  background: rgba(232, 163, 61, 0.06);
}
.current-task > div {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.current-task b {
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.current-task small {
  font-size: 9.5px;
}
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4fd1b0;
  flex: 0 0 auto;
}
.task-mini-list {
  margin-top: 9px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.task-mini {
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  color: var(--text);
  text-align: left;
  padding: 5px 2px;
  cursor: pointer;
  border-bottom: 1px dashed var(--line);
}
.task-mini:last-child {
  border-bottom: none;
}
.task-mini > span:first-child {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.task-mini b {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-mini small {
  font-size: 9px;
}
.task-mini > .mono {
  font-size: 9.5px;
  color: var(--dim);
}
.agent-view-top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.agent-mark {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
}
.agent-view-top > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.agent-view-top b {
  font-size: 12px;
}
.agent-view-top small {
  font-size: 9.5px;
  color: var(--dim);
}
.agent-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}
.tag {
  font-size: 9.5px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 6px;
}
.agent-caps {
  margin: 7px 0 0;
  font-size: 10px;
  line-height: 1.5;
}
.radar-panel {
  display: flex;
  flex-direction: column;
}
.empty-line {
  padding: 14px 0;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.project-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.project-chip {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  color: var(--text);
  text-align: left;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
}
.project-chip b {
  font-size: 11.5px;
}
.project-chip small {
  font-size: 9.5px;
  color: var(--dim);
}
.projects-head {
  margin-bottom: 0;
}
.head-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 9px;
}
.project-card {
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel);
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.project-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.project-card-head b {
  font-size: 12.5px;
}
.project-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10px;
  color: var(--dim);
  border-top: 1px dashed var(--line);
  padding-top: 6px;
}
.project-actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 9px;
}
.config-card {
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.config-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.config-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.1);
  color: var(--amber);
}
.config-icon :deep(svg) {
  width: 16px;
  height: 16px;
}
.config-head > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.config-head b {
  font-size: 12px;
}
.config-head small {
  font-size: 9.5px;
  color: var(--dim);
}
.config-card p {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  flex: 1;
}
.config-card .btn {
  align-self: flex-start;
}
.wb-empty {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  text-align: center;
  color: var(--dim);
}
.wb-empty :deep(svg) {
  width: 34px;
  height: 34px;
  color: var(--amber);
}
.wb-empty b {
  color: var(--text);
}
.wb-loading {
  padding: 24px;
  font-size: 12px;
}
.workbench-chat {
  position: sticky;
  top: 12px;
  height: calc(100vh - 130px);
}
@media (max-width: 1360px) {
  .workbench-layout {
    grid-template-columns: 232px minmax(0, 1fr);
  }
  .workbench-chat {
    display: none;
  }
  .overview-grid {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  .radar-panel {
    grid-column: 1 / -1;
  }
}
@media (max-width: 900px) {
  .workbench-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .roster {
    position: static;
    max-height: 260px;
  }
  .metric-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .overview-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
