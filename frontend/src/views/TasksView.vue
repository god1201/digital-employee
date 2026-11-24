<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import TaskDetailDrawer from "@/components/TaskDetailDrawer.vue";
import TaskReplayDrawer from "@/components/TaskReplayDrawer.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface Definition {
  id: number;
  name: string;
  code: string;
  task_type: string;
  steps: unknown[];
  version: number;
  enabled: boolean;
  created_at: string;
}

interface TaskInstance {
  id: number;
  title: string;
  trace_id?: string;
  employee_id?: number | null;
  task_type: string;
  status: string;
  attempt: number;
  max_attempts: number;
  current_step_index: number;
  created_at: string;
}

interface Collaboration {
  id: number;
  owner_employee_id: number;
  goal: string;
  mode: string;
  participants: Array<{ employee_id: number; name?: string; instruction?: string }>;
  parent_instance_id?: number | null;
  status: string;
  created_at: string;
}

interface TaskTrigger {
  id: number;
  employee_id: number;
  definition_id?: number | null;
  name: string;
  trigger_type: string;
  interval_seconds?: number | null;
  daily_at?: string | null;
  event_name?: string | null;
  enabled: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at: string;
}

const employees = ref<Employee[]>([]);
const definitions = ref<Definition[]>([]);
const instances = ref<TaskInstance[]>([]);
const collaborations = ref<Collaboration[]>([]);
const triggers = ref<TaskTrigger[]>([]);
const tab = ref<
  "instances" | "definitions" | "collaborations" | "triggers"
>("instances");
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

const employeeMap = computed(() =>
  Object.fromEntries(employees.value.map((item) => [item.id, item.name])),
);

async function load(): Promise<void> {
  try {
    const [
      employeeData,
      definitionData,
      instanceData,
      collaborationData,
      triggerData,
    ] = await Promise.all([
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
      api.get<Paged<Definition>>("/tasks/definitions?page_size=200"),
      api.get<Paged<TaskInstance>>("/tasks/instances?page_size=200"),
      api.get<Paged<Collaboration>>("/collaborations?page_size=200"),
      api.get<Paged<TaskTrigger>>("/task-triggers?page_size=200"),
    ]);
    employees.value = employeeData.items;
    definitions.value = definitionData.items;
    instances.value = instanceData.items;
    collaborations.value = collaborationData.items;
    triggers.value = triggerData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function openDetail(row: TaskInstance): void {
  drawer.open(TaskDetailDrawer, {
    id: row.id,
    employeeName: row.employee_id ? employeeMap.value[row.employee_id] : "—",
    onChanged: load,
  });
}

function openReplay(row: TaskInstance): void {
  drawer.open(TaskReplayDrawer, {
    id: row.id,
    employeeName: row.employee_id ? employeeMap.value[row.employee_id] : "—",
  });
}

function openCollaborationTask(row: Collaboration): void {
  if (!row.parent_instance_id) {
    toast.push("协作文档尚未生成任务实例", "error");
    return;
  }
  drawer.open(TaskDetailDrawer, {
    id: row.parent_instance_id,
    employeeName: employeeMap.value[row.owner_employee_id] || "—",
    onChanged: load,
  });
}

function createTrigger(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "新建任务触发器",
    sub: "定时/每日触发器用于主动汇报与周期任务；事件触发器可由外部系统调用。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "执行员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      {
        name: "definition_id",
        label: "任务定义",
        type: "select",
        numeric: true,
        options: [
          { value: "", label: "自由任务（需要 LLM）" },
          ...definitions.value.map((item) => ({
            value: item.id,
            label: `${item.name} · ${item.task_type}`,
          })),
        ],
      },
      { name: "name", label: "触发器名称", required: true, placeholder: "每日回款日报" },
      {
        name: "trigger_type",
        label: "类型",
        type: "select",
        options: [
          { value: "interval", label: "间隔执行" },
          { value: "daily", label: "每日定时" },
          { value: "event", label: "事件触发" },
        ],
        value: "daily",
      },
      { name: "interval_seconds", label: "间隔秒数", type: "number", value: 3600 },
      { name: "daily_at", label: "每日时间（UTC HH:MM）", placeholder: "18:00" },
      { name: "event_name", label: "事件名", placeholder: "invoice.received" },
      { name: "input", label: "任务输入（JSON）", type: "json", value: {} },
      {
        name: "enabled",
        label: "启用",
        type: "select",
        options: [
          { value: "true", label: "启用" },
          { value: "false", label: "停用" },
        ],
        value: "true",
      },
    ],
    submitLabel: "创建触发器",
    onSubmit: async (values) => {
      await api.post("/task-triggers", {
        employee_id: values.employee_id,
        definition_id: values.definition_id || null,
        name: values.name,
        trigger_type: values.trigger_type,
        interval_seconds:
          values.trigger_type === "interval" ? values.interval_seconds : null,
        daily_at: values.trigger_type === "daily" ? values.daily_at || null : null,
        event_name:
          values.trigger_type === "event" ? values.event_name || null : null,
        input: values.input || {},
        enabled: String(values.enabled) === "true",
      });
      toast.push("触发器已创建");
      tab.value = "triggers";
      await load();
    },
  });
}

async function fireTrigger(row: TaskTrigger): Promise<void> {
  try {
    const result = await api.post<any>(`/task-triggers/${row.id}/fire`, {});
    toast.push(`已触发，任务 #${result.instance_id}`);
    await load();
    drawer.open(TaskDetailDrawer, {
      id: result.instance_id,
      employeeName: employeeMap.value[row.employee_id] || "—",
      onChanged: load,
    });
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "触发失败", "error");
  }
}

async function toggleTrigger(row: TaskTrigger): Promise<void> {
  try {
    await api.patch(`/task-triggers/${row.id}`, { enabled: !row.enabled });
    toast.push(row.enabled ? "触发器已停用" : "触发器已启用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function triggerSchedule(row: TaskTrigger): string {
  if (row.trigger_type === "interval") return `每 ${row.interval_seconds ?? 0}s`;
  if (row.trigger_type === "daily") return `每日 ${row.daily_at} UTC`;
  return row.event_name || "事件";
}

function startCollaboration(): void {
  if (employees.value.length < 2) {
    toast.push("多员工协作至少需要两个数字员工", "error");
    return;
  }
  const suggested = [
    { employee_id: employees.value[0].id, instruction: "负责客户 A 的核对" },
    { employee_id: employees.value[1].id, instruction: "负责客户 B 的核对" },
  ];
  modal.openForm({
    title: "发起多员工协作",
    sub: "参与者会依次拿到子任务；可传 steps 固定子任务步骤，为空则由员自由规划（需要 LLM）。",
    wide: true,
    fields: [
      {
        name: "owner_employee_id",
        label: "负责人",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      { name: "goal", label: "协作目标", type: "textarea", required: true, rows: 3 },
      {
        name: "mode",
        label: "执行模式",
        type: "select",
        options: [
          { value: "sequential", label: "顺序委派（后者可参考前者结果）" },
          { value: "parallel", label: "并行协作（同时执行再汇总）" },
        ],
        value: "sequential",
      },
      {
        name: "participants",
        label: "参与者（JSON 数组）",
        type: "json",
        value: suggested,
        help: '每项支持 employee_id、employee_code、instruction，可选 steps。',
      },
      {
        name: "summarize",
        label: "最后汇总",
        type: "select",
        options: [
          { value: "false", label: "不汇总（仅保留各员工结果）" },
          { value: "true", label: "由负责人用 LLM 汇总" },
        ],
        value: "false",
      },
    ],
    submitLabel: "发起协作",
    onSubmit: async (values) => {
      if (!Array.isArray(values.participants) || !values.participants.length) {
        throw new Error("参与者必须是非空 JSON 数组");
      }
      const result = await api.post<any>("/collaborations", {
        owner_employee_id: values.owner_employee_id,
        goal: values.goal,
        mode: values.mode,
        participants: values.participants,
        summarize: String(values.summarize) === "true",
      });
      toast.push("协作任务已创建");
      await load();
      if (result.parent_instance_id) {
        drawer.open(TaskDetailDrawer, {
          id: result.parent_instance_id,
          employeeName: employeeMap.value[result.owner_employee_id] || "—",
          onChanged: load,
        });
      }
    },
  });
}

function createTask(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "发起任务",
    sub: "选择员工和任务定义；自由任务需要配置 LLM_API_KEY。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "执行员工",
        type: "select",
        required: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      {
        name: "definition_id",
        label: "任务定义",
        type: "select",
        options: [
          { value: "", label: "自由任务（由大模型规划）" },
          ...definitions.value.map((item) => ({
            value: item.id,
            label: `${item.name} · ${item.task_type}`,
          })),
        ],
      },
      { name: "title", label: "标题", placeholder: "留空则使用定义名称" },
      { name: "max_attempts", label: "最大尝试", type: "number", value: 3 },
      { name: "priority", label: "优先级", type: "number", value: 100 },
      { name: "input", label: "输入 JSON", type: "json", full: true, value: {} },
    ],
    submitLabel: "发起任务",
    onSubmit: async (values) => {
      await api.post("/tasks/instances", {
        employee_id: Number(values.employee_id),
        definition_id: values.definition_id ? Number(values.definition_id) : null,
        title: values.title || null,
        input: values.input,
        max_attempts: Number(values.max_attempts || 3),
        priority: Number(values.priority || 100),
      });
      toast.push("任务已进入队列");
      await load();
    },
  });
}

function createDefinition(): void {
  modal.openForm({
    title: "新建任务定义",
    sub: "固定任务按步骤执行；工具步骤使用 tool_code，人工步骤使用 type=human。",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true },
      { name: "code", label: "编码", required: true, placeholder: "content_review" },
      {
        name: "task_type",
        label: "类型",
        type: "select",
        options: ["fixed", "free"],
        value: "fixed",
      },
      {
        name: "employee_id",
        label: "绑定员工",
        type: "select",
        options: [
          { value: "", label: "不绑定" },
          ...employees.value.map((item) => ({ value: item.id, label: item.name })),
        ],
      },
      { name: "description", label: "说明", type: "textarea", rows: 2 },
      {
        name: "steps",
        label: "步骤 JSON",
        type: "json",
        full: true,
        value: [{ name: "人工确认", type: "human", description: "确认执行结果" }],
      },
    ],
    submitLabel: "创建定义",
    onSubmit: async (values) => {
      await api.post("/tasks/definitions", {
        name: values.name,
        code: values.code,
        task_type: values.task_type,
        employee_id: values.employee_id ? Number(values.employee_id) : null,
        description: values.description,
        steps: values.steps,
      });
      toast.push("任务定义已创建");
      tab.value = "definitions";
      await load();
    },
  });
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="operations / tasks"
    title="任务中心"
    sub="发起任务、观察步骤轨迹、在关键节点介入。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="createDefinition">
        <AppIcon name="plus" />新建定义
      </button>
      <button class="btn btn-ghost" @click="createTrigger">
        <AppIcon name="clock" />新建触发器
      </button>
      <button class="btn btn-ghost" @click="startCollaboration">
        <AppIcon name="users" />发起协作
      </button>
      <button class="btn btn-primary" @click="createTask"><AppIcon name="play" />发起任务</button>
    </template>
  </PageHeader>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'instances' }" @click="tab = 'instances'">
      任务实例 <span class="dim">{{ instances.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'definitions' }" @click="tab = 'definitions'">
      任务定义 <span class="dim">{{ definitions.length }}</span>
    </button>
    <button
      class="tab"
      :class="{ active: tab === 'collaborations' }"
      @click="tab = 'collaborations'"
    >
      多员工协作 <span class="dim">{{ collaborations.length }}</span>
    </button>
    <button
      class="tab"
      :class="{ active: tab === 'triggers' }"
      @click="tab = 'triggers'"
    >
      触发器 <span class="dim">{{ triggers.length }}</span>
    </button>
  </div>

  <div class="panel">
    <DataTable
      v-if="tab === 'instances'"
      :rows="instances"
      :columns="[
        { label: '任务', format: (row) => `<div class='cell-main'><b>${esc(row.title)}</b><small>#${row.id} · ${esc(row.trace_id || '')}</small></div>` },
        { label: '员工', format: (row) => esc(employeeMap[row.employee_id] || '—') },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.task_type)}</span>` },
        { label: '状态', key: 'status' },
        { label: '尝试', format: (row) => `<span class='mono'>${row.attempt} / ${row.max_attempts}</span>` },
        { label: '步骤', format: (row) => `<span class='mono'>${Number(row.current_step_index || 0) + 1}</span>` },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有任务实例"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openDetail(row)">详情</button>
          <button class="btn btn-sm btn-ghost" @click="openReplay(row)">回放</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'definitions'"
      :rows="definitions"
      :columns="[
        { label: '定义', format: (row) => `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(row.code)}</small></div>` },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.task_type)}</span>` },
        { label: '步骤', format: (row) => `<span class='mono'>${(row.steps || []).length}</span>` },
        { label: '版本', format: (row) => `<span class='mono'>v${row.version}</span>` },
        { label: '状态', key: 'status' },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
      ]"
      empty-text="还没有任务定义"
    >
      <template #cell-status="{ row }">
        <StatusPill :status="row.enabled ? 'active' : 'disabled'" />
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'collaborations'"
      :rows="collaborations"
      :columns="[
        {
          label: '协作',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.goal)}</b><small>#${row.id} · parent #${row.parent_instance_id ?? '—'}</small></div>`,
        },
        { label: '负责人', format: (row) => esc(employeeMap[row.owner_employee_id] || '—') },
        { label: '模式', format: (row) => `<span class='tag'>${esc(row.mode)}</span>` },
        { label: '参与者', format: (row) => `<span class='mono'>${(row.participants || []).length}</span>` },
        { label: '状态', key: 'status' },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有协作会话。发起一次，让多个数字员工接力。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openCollaborationTask(row)">查看任务</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else
      :rows="triggers"
      :columns="[
        {
          label: '触发器',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small>#${row.id} · ${esc(employeeMap[row.employee_id] || '')}</small></div>`,
        },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.trigger_type)}</span>` },
        { label: '计划', format: (row) => `<span class='mono'>${esc(triggerSchedule(row))}</span>` },
        { label: '状态', format: (row) => `<span class='tag'>${row.enabled ? '启用' : '停用'}</span>` },
        { label: '下次', format: (row) => `<span class='muted'>${fmtDate(row.next_run_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有触发器。用每日触发器做主动汇报，用事件触发器接外部 webhook。"
    >
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-primary" @click="fireTrigger(row)">触发</button>
          <button class="btn btn-sm btn-ghost" @click="toggleTrigger(row)">
            {{ row.enabled ? "停用" : "启用" }}
          </button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
