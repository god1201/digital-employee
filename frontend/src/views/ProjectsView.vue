<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";

interface Project {
  id: number;
  name: string;
  code: string;
  description: string;
  status: string;
  owner_employee_id?: number | null;
  owner_name?: string | null;
  member_count?: number;
  task_count?: number;
  conversation_count?: number;
  token_budget?: number | null;
  token_usage?: {
    tokens?: number;
    cost?: number;
    task_tokens?: number;
    chat_tokens?: number;
    budget?: number | null;
  } | null;
}

const route = useRoute();
const router = useRouter();
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

const rows = ref<Project[]>([]);
const loading = ref(false);
const error = ref("");
const keyword = ref("");
const statusFilter = ref("active");
const view = ref<"cards" | "board">("cards");

const statusTabs = [
  { value: "active", label: "进行中" },
  { value: "paused", label: "已暂停" },
  { value: "archived", label: "已归档" },
  { value: "", label: "全部" },
];

const statusLabels: Record<string, string> = {
  active: "进行中",
  paused: "已暂停",
  archived: "已归档",
};

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  return rows.value.filter((project) => {
    if (statusFilter.value && project.status !== statusFilter.value) return false;
    if (!text) return true;
    return [project.name, project.code, project.description, project.owner_name]
      .join(" ")
      .toLowerCase()
      .includes(text);
  });
});

const boardColumns = computed(() =>
  ["active", "paused", "archived"].map((status) => ({
    status,
    label: statusLabels[status],
    items: filtered.value.filter((project) => project.status === status),
  })),
);

function tokenText(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value ?? 0);
}

function budgetRatio(project: Project): number {
  const budget = Number(project.token_budget || project.token_usage?.budget || 0);
  if (!budget) return 0;
  return Math.min(100, (Number(project.token_usage?.tokens || 0) / budget) * 100);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    rows.value = await api.get<Project[]>("/projects");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载项目失败";
  } finally {
    loading.value = false;
  }
}

function openProjectById(projectId: number): void {
  drawer.open(ProjectDetailDrawer, { projectId, onChanged: load });
}

function openProject(project: Project): void {
  if (String(route.query.project || "") === String(project.id)) {
    openProjectById(project.id);
    return;
  }
  // 先写入 query，由 watch 统一打开抽屉，避免重复打开。
  void router.replace({ query: { ...route.query, project: String(project.id) } });
}

function createProject(): void {
  modal.openForm({
    title: "新建项目",
    sub: "项目把任务、会话与 Token 成本组织到同一业务目标下。",
    wide: true,
    fields: [
      { name: "name", label: "项目名称", required: true, placeholder: "例如：Q4 回款专项" },
      { name: "code", label: "编码", required: true, placeholder: "q4_collection" },
      {
        name: "status",
        label: "状态",
        type: "select",
        options: [
          { value: "active", label: "进行中" },
          { value: "paused", label: "已暂停" },
        ],
      },
      {
        name: "token_budget",
        label: "Token 预算（0 表示不限制）",
        type: "number",
        value: 0,
      },
      { name: "description", label: "描述", type: "textarea", rows: 3, full: true },
    ],
    submitLabel: "创建项目",
    onSubmit: async (values) => {
      const project = await api.post<Project>("/projects", {
        name: values.name,
        code: values.code,
        status: values.status || "active",
        token_budget: Number(values.token_budget) || 0,
        description: values.description || "",
      });
      toast.push("项目已创建");
      await load();
      openProject(project);
    },
  });
}

watch(
  () => route.query.project,
  (value) => {
    const id = Number(value);
    if (id) openProjectById(id);
  },
);

onMounted(async () => {
  await load();
  const queryId = Number(route.query.project);
  if (queryId) openProjectById(queryId);
});
</script>

<template>
  <PageHeader
    eyebrow="organization / projects"
    title="项目"
    sub="把任务、会话与数字员工组织到同一业务目标，按项目核算 Token 与成本。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="createProject"><AppIcon name="plus" />新建项目</button>
    </template>
  </PageHeader>

  <div class="toolbar panel">
    <div class="filter-search">
      <AppIcon name="search" />
      <input v-model="keyword" placeholder="搜索项目名称、编码、负责人" />
    </div>
    <div class="tabs status-tabs">
      <button
        v-for="tab in statusTabs"
        :key="tab.value"
        type="button"
        class="tab"
        :class="{ active: statusFilter === tab.value }"
        @click="statusFilter = tab.value"
      >
        {{ tab.label }}
      </button>
    </div>
    <div class="view-toggle">
      <button
        type="button"
        class="toggle-btn"
        :class="{ active: view === 'cards' }"
        @click="view = 'cards'"
      >
        卡片
      </button>
      <button
        type="button"
        class="toggle-btn"
        :class="{ active: view === 'board' }"
        @click="view = 'board'"
      >
        看板
      </button>
    </div>
  </div>

  <div v-if="loading" class="panel loading-panel muted">加载项目…</div>
  <div v-else-if="error" class="panel loading-panel">
    <span class="error-text">{{ error }}</span>
    <button class="btn btn-sm" @click="load">重试</button>
  </div>

  <template v-else>
    <div v-if="!filtered.length" class="panel empty-panel">
      <p>{{ rows.length ? "当前筛选下没有项目。" : "还没有项目。" }}</p>
      <p class="muted">
        新建项目后，可以把员工任务与会话归集进来，统一核算 Token 与成本。
      </p>
      <button class="btn btn-primary" @click="createProject"><AppIcon name="plus" />新建项目</button>
    </div>

    <div v-else-if="view === 'cards'" class="project-grid">
      <button
        v-for="project in filtered"
        :key="project.id"
        type="button"
        class="project-card"
        @click="openProject(project)"
      >
        <div class="card-head">
          <b>{{ project.name }}</b>
          <StatusPill
            :status="project.status"
            :text="statusLabels[project.status] || project.status"
          />
        </div>
        <small class="mono">{{ project.code }}</small>
        <p v-if="project.description" class="card-desc">{{ project.description }}</p>

        <div class="stat-row">
          <span><b>{{ project.member_count ?? 0 }}</b> 成员</span>
          <span><b>{{ project.task_count ?? 0 }}</b> 任务</span>
          <span><b>{{ project.conversation_count ?? 0 }}</b> 会话</span>
        </div>

        <div v-if="project.token_budget" class="budget-mini">
          <div class="budget-track">
            <div
              class="budget-fill"
              :class="{ over: budgetRatio(project) >= 100 }"
              :style="{ width: `${budgetRatio(project)}%` }"
            />
          </div>
          <span class="muted mono">
            {{ tokenText(project.token_usage?.tokens || 0) }} /
            {{ tokenText(project.token_budget || 0) }}
          </span>
        </div>

        <div class="card-foot">
          <span class="muted">负责人 · {{ project.owner_name || "未指定" }}</span>
          <span class="mono muted">{{ tokenText(project.token_usage?.tokens || 0) }} tokens</span>
        </div>
      </button>
    </div>

    <div v-else class="board">
      <section v-for="column in boardColumns" :key="column.status" class="board-column">
        <div class="board-head">
          <b>{{ column.label }}</b>
          <span class="mono muted">{{ column.items.length }}</span>
        </div>
        <div class="board-body">
          <button
            v-for="project in column.items"
            :key="project.id"
            type="button"
            class="board-card"
            @click="openProject(project)"
          >
            <div class="card-head">
              <b>{{ project.name }}</b>
              <span class="mono muted">{{ project.code }}</span>
            </div>
            <div class="stat-row">
              <span>{{ project.member_count ?? 0 }} 成员</span>
              <span>{{ project.task_count ?? 0 }} 任务</span>
              <span>{{ tokenText(project.token_usage?.tokens || 0) }} tokens</span>
            </div>
            <div class="card-foot">
              <span class="muted">{{ project.owner_name || "未指定负责人" }}</span>
            </div>
          </button>
          <div v-if="!column.items.length" class="board-empty muted">暂无项目</div>
        </div>
      </section>
    </div>
  </template>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.filter-search {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 10px;
  height: 34px;
  background: var(--panel-2);
  min-width: 240px;
  flex: 1;
}
.filter-search :deep(svg) {
  width: 15px;
  height: 15px;
  color: var(--dim);
}
.filter-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 12px;
}
.status-tabs {
  flex-shrink: 0;
}
.view-toggle {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
  flex-shrink: 0;
}
.toggle-btn {
  border: none;
  background: transparent;
  color: var(--dim);
  font-size: 11px;
  padding: 6px 12px;
  cursor: pointer;
}
.toggle-btn.active {
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
}
.loading-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 22px;
  font-size: 12px;
}
.error-text {
  color: var(--coral);
}
.empty-panel {
  padding: 36px;
  text-align: center;
  font-size: 12.5px;
  line-height: 1.8;
}
.empty-panel p {
  margin: 0 0 6px;
}
.empty-panel .btn {
  margin-top: 14px;
}
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.project-card {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}
.project-card:hover {
  border-color: var(--amber);
  transform: translateY(-1px);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-head b {
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-desc {
  margin: 0;
  font-size: 11px;
  color: var(--dim);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 10.5px;
  color: var(--dim);
  margin-top: 2px;
}
.stat-row b {
  color: var(--text);
  font-family: var(--mono);
  font-size: 11.5px;
}
.budget-mini {
  display: flex;
  align-items: center;
  gap: 9px;
}
.budget-mini .budget-track {
  flex: 1;
}
.budget-mini span {
  font-size: 10px;
  white-space: nowrap;
}
.budget-track {
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}
.budget-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--amber);
}
.budget-fill.over {
  background: var(--coral);
}
.card-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 10px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
  margin-top: 2px;
}
.board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  align-items: start;
}
.board-column {
  border: 1px solid var(--line);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.012);
  padding: 10px;
}
.board-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 4px 9px;
  font-size: 11.5px;
}
.board-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 80px;
}
.board-card {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
}
.board-card:hover {
  border-color: var(--amber);
}
.board-card .card-head {
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.board-card .stat-row {
  gap: 8px;
}
.board-empty {
  padding: 16px;
  text-align: center;
  font-size: 11px;
  border: 1px dashed var(--line);
  border-radius: 10px;
}
@media (max-width: 1100px) {
  .board {
    grid-template-columns: 1fr;
  }
}
</style>
