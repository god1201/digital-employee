<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import ConversationLinkModal from "@/components/ConversationLinkModal.vue";
import EmployeePickerModal from "@/components/EmployeePickerModal.vue";
import StatusPill from "@/components/StatusPill.vue";
import TaskLinkModal from "@/components/TaskLinkModal.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{
  projectId: number;
  onChanged?: () => void;
}>();

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const router = useRouter();

const detail = ref<any>(null);
const employees = ref<any[]>([]);
const loading = ref(true);
const error = ref("");

const project = computed(() => detail.value?.project || null);
const members = computed(() => detail.value?.members || []);
const tasks = computed(() => detail.value?.tasks || []);
const conversations = computed(() => detail.value?.conversations || []);
const tokenUsage = computed(() => detail.value?.token_usage || {});
const budget = computed(() => Number(project.value?.token_budget || 0));
const budgetRatio = computed(() => {
  if (!budget.value) return 0;
  return Math.min(100, (Number(tokenUsage.value.tokens || 0) / budget.value) * 100);
});

const statusLabels: Record<string, string> = {
  active: "进行中",
  paused: "已暂停",
  archived: "已归档",
};

const roleLabels: Record<string, string> = {
  owner: "负责人",
  reviewer: "评审",
  member: "成员",
};

const modeLabels: Record<string, string> = {
  direct: "直接对话",
  group: "群聊",
};

function tokenText(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value ?? 0);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [projectDetail, employeeData] = await Promise.all([
      api.get<any>(`/projects/${props.projectId}`),
      api.get<Paged<any>>("/digital-employees?page_size=200&status=active"),
    ]);
    detail.value = projectDetail;
    employees.value = employeeData.items;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载项目失败";
  } finally {
    loading.value = false;
  }
}

async function refresh(): Promise<void> {
  await load();
  props.onChanged?.();
}

function editProject(): void {
  const current = project.value;
  if (!current) return;
  modal.openForm({
    title: "编辑项目",
    sub: "调整项目名称、状态与 Token 预算。",
    fields: [
      { name: "name", label: "项目名称", value: current.name, required: true },
      {
        name: "status",
        label: "状态",
        type: "select",
        value: current.status,
        options: [
          { value: "active", label: "进行中" },
          { value: "paused", label: "已暂停" },
          { value: "archived", label: "已归档" },
        ],
      },
      { name: "token_budget", label: "Token 预算（0 表示不限制）", type: "number", value: current.token_budget || 0 },
      { name: "description", label: "描述", type: "textarea", rows: 3, full: true, value: current.description || "" },
    ],
    submitLabel: "保存",
    onSubmit: async (values) => {
      await api.patch(`/projects/${props.projectId}`, {
        name: values.name,
        status: values.status,
        token_budget: Number(values.token_budget) || 0,
        description: values.description || "",
      });
      toast.push("项目已更新");
      await refresh();
    },
  });
}

function addMember(): void {
  const memberIds = members.value.map((member: any) => member.employee_id);
  modal.openCustom(EmployeePickerModal, {
    employees: employees.value,
    excludeIds: memberIds,
    title: "添加项目成员",
    sub: "成员可参与项目任务；负责人用于归属展示。",
    submitLabel: "添加成员",
    onSelect: async (employee: any) => {
      try {
        await api.post(`/projects/${props.projectId}/members`, {
          employee_id: employee.id,
          role: "member",
        });
        toast.push(`已添加成员：${employee.name}`);
        await refresh();
      } catch (err) {
        toast.push(err instanceof Error ? err.message : "添加成员失败", "error");
      }
    },
  });
}

async function removeMember(member: any): Promise<void> {
  if (!window.confirm(`确认把 ${member.name || member.employee_id} 移出项目？`)) return;
  try {
    await api.delete(`/projects/${props.projectId}/members/${member.employee_id}`);
    toast.push("成员已移除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "移除成员失败", "error");
  }
}

function linkTask(): void {
  modal.openCustom(TaskLinkModal, {
    projectId: props.projectId,
    projectName: project.value?.name,
    onLinked: refresh,
  });
}

async function unlinkTask(task: any): Promise<void> {
  try {
    await api.delete(`/projects/${props.projectId}/tasks/${task.id}`);
    toast.push("任务已取消关联");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "取消关联失败", "error");
  }
}

function linkConversation(): void {
  modal.openCustom(ConversationLinkModal, {
    projectId: props.projectId,
    projectName: project.value?.name,
    onLinked: refresh,
  });
}

async function unlinkConversation(item: any): Promise<void> {
  try {
    await api.delete(`/projects/${props.projectId}/conversations/${item.id}`);
    toast.push("会话已取消关联");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "取消关联失败", "error");
  }
}

function openMemberWorkbench(member: any): void {
  drawer.close();
  void router.push({
    name: "employees",
    query: { employee: String(member.employee_id) },
  });
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ project?.name || "项目详情" }}</h3>
      <p class="mono">
        {{ project?.code || "" }}
        <template v-if="project">· {{ statusLabels[project.status] || project.status }}</template>
      </p>
    </div>
    <div class="head-actions">
      <button class="btn btn-sm btn-ghost" type="button" @click="editProject">编辑</button>
      <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
        <AppIcon name="close" />
      </button>
    </div>
  </div>

  <div v-if="loading" class="muted drawer-hint">加载中…</div>
  <div v-else-if="error" class="drawer-error">
    <p>{{ error }}</p>
    <button class="btn btn-sm" type="button" @click="load">重试</button>
  </div>

  <template v-else-if="project">
    <p v-if="project.description" class="project-desc">{{ project.description }}</p>

    <div class="metric-grid">
      <div class="metric">
        <span>Token</span>
        <b>{{ tokenText(tokenUsage.tokens || 0) }}</b>
      </div>
      <div class="metric">
        <span>成本</span>
        <b>{{ Number(tokenUsage.cost || 0).toFixed(4) }}</b>
      </div>
      <div class="metric">
        <span>任务 / 会话</span>
        <b>{{ tasks.length }} / {{ conversations.length }}</b>
      </div>
    </div>

    <div class="budget-block">
      <div class="budget-head">
        <span>预算使用</span>
        <span class="mono">
          {{ tokenText(tokenUsage.tokens || 0) }} /
          {{ budget ? tokenText(budget) : "不限制" }}
        </span>
      </div>
      <div class="budget-track">
        <div class="budget-fill" :class="{ over: budgetRatio >= 100 }" :style="{ width: `${budgetRatio}%` }" />
      </div>
      <div class="budget-legend muted">
        任务 {{ tokenText(tokenUsage.task_tokens || 0) }} · 会话 {{ tokenText(tokenUsage.chat_tokens || 0) }}
      </div>
    </div>

    <div class="section-row">
      <span class="section-label">成员 · {{ members.length }}</span>
      <button class="btn btn-sm" type="button" @click="addMember"><AppIcon name="plus" />添加成员</button>
    </div>
    <div v-if="members.length" class="member-list">
      <div v-for="member in members" :key="member.employee_id" class="member-row">
        <button type="button" class="member-main" @click="openMemberWorkbench(member)">
          <span class="avatar">{{ (member.name || "员").slice(0, 1) }}</span>
          <span class="member-meta">
            <b>{{ member.name || `员工 ${member.employee_id}` }}</b>
            <small class="muted">{{ member.position || "未设置岗位" }}</small>
          </span>
        </button>
        <span class="tag">{{ roleLabels[member.role] || member.role }}</span>
        <button
          v-if="member.role !== 'owner'"
          class="icon-btn small"
          type="button"
          title="移出项目"
          @click="removeMember(member)"
        >
          <AppIcon name="close" />
        </button>
      </div>
    </div>
    <div v-else class="empty-line muted">还没有成员。</div>

    <div class="section-row">
      <span class="section-label">关联任务 · {{ tasks.length }}</span>
      <button class="btn btn-sm" type="button" @click="linkTask"><AppIcon name="plus" />关联任务</button>
    </div>
    <div v-if="tasks.length" class="linked-list">
      <div v-for="task in tasks" :key="task.id" class="linked-row">
        <span class="linked-main">
          <b>{{ task.title }}</b>
          <small class="mono">#{{ task.id }} · {{ task.task_type }}</small>
        </span>
        <StatusPill :status="task.status" />
        <span class="mono tokens">{{ tokenText(task.tokens || 0) }}</span>
        <span class="muted date">{{ fmtDate(task.created_at) }}</span>
        <button class="btn btn-sm btn-ghost" type="button" @click="unlinkTask(task)">取消关联</button>
      </div>
    </div>
    <div v-else class="empty-line muted">还没有关联任务。</div>

    <div class="section-row">
      <span class="section-label">关联会话 · {{ conversations.length }}</span>
      <button class="btn btn-sm" type="button" @click="linkConversation"><AppIcon name="plus" />关联会话</button>
    </div>
    <div v-if="conversations.length" class="linked-list">
      <div v-for="item in conversations" :key="item.id" class="linked-row">
        <span class="linked-main">
          <b>{{ item.title || `会话 #${item.id}` }}</b>
          <small class="mono">#{{ item.id }} · {{ modeLabels[item.mode] || item.mode }}</small>
        </span>
        <span class="muted date">
          {{ item.last_message_at ? fmtDate(item.last_message_at) : "暂无消息" }}
        </span>
        <button class="btn btn-sm btn-ghost" type="button" @click="unlinkConversation(item)">取消关联</button>
      </div>
    </div>
    <div v-else class="empty-line muted">还没有关联会话。</div>
  </template>
</template>

<style scoped>
.head-actions {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.drawer-hint {
  padding: 20px 0;
  font-size: 12px;
}
.drawer-error {
  border: 1px solid color-mix(in srgb, var(--coral) 40%, var(--line));
  border-radius: 10px;
  padding: 14px;
  font-size: 12px;
  color: var(--coral);
}
.drawer-error p {
  margin: 0 0 10px;
}
.project-desc {
  margin: 0 0 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--dim);
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.metric {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric span {
  font-size: 10.5px;
  color: var(--dim);
}
.metric b {
  font-family: var(--mono);
  font-size: 14px;
}
.budget-block {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 11px 12px;
}
.budget-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 11px;
  color: var(--dim);
  margin-bottom: 8px;
}
.budget-track {
  height: 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}
.budget-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--amber);
  transition: width 0.3s;
}
.budget-fill.over {
  background: var(--coral);
}
.budget-legend {
  margin-top: 7px;
  font-size: 10px;
}
.section-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 22px 0 9px;
}
.section-label {
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--dim);
}
.member-list,
.linked-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.member-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 28px;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 7px 9px;
}
.member-main {
  display: flex;
  align-items: center;
  gap: 9px;
  border: none;
  background: transparent;
  color: var(--text);
  text-align: left;
  padding: 0;
  cursor: pointer;
}
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
  font-size: 11.5px;
  flex-shrink: 0;
}
.member-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.member-meta b {
  font-size: 12px;
}
.member-meta small {
  font-size: 10px;
}
.icon-btn.small {
  width: 24px;
  height: 24px;
}
.icon-btn.small :deep(svg) {
  width: 12px;
  height: 12px;
}
.linked-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto auto;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 8px 10px;
}
.linked-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.linked-main b {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.linked-main small {
  font-size: 10px;
  color: var(--dim);
}
.tokens {
  font-size: 11px;
  color: var(--dim);
}
.date {
  font-size: 10.5px;
  white-space: nowrap;
}
.empty-line {
  font-size: 11.5px;
  padding: 8px 0 2px;
}
.tag {
  font-size: 10px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
  white-space: nowrap;
}
@media (max-width: 560px) {
  .linked-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .linked-row .tokens,
  .linked-row .date {
    display: none;
  }
}
</style>
