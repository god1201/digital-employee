<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface PreferencePair {
  id: number;
  employee_id?: number | null;
  source_type: string;
  source_ref: string;
  prompt: string;
  chosen: string;
  rejected: string;
  status: string;
  created_at: string;
}

interface TrainingJob {
  id: number;
  employee_id?: number | null;
  method: string;
  dataset_path: string;
  dataset_size: number;
  status: string;
  metrics: Record<string, any>;
  error?: string | null;
  created_at: string;
}

const tab = ref<"pairs" | "jobs">("pairs");
const pairs = ref<PreferencePair[]>([]);
const jobs = ref<TrainingJob[]>([]);
const employees = ref<Employee[]>([]);
const loading = ref(false);
const lastExport = ref("");

const modal = useModalStore();
const toast = useToastStore();

const employeeMap = computed(() =>
  Object.fromEntries(employees.value.map((item) => [item.id, item.name])),
);

const employeeOptions = computed(() => [
  { value: "", label: "全部员工 / 不绑定" },
  ...employees.value.map((item) => ({
    value: item.id,
    label: `${item.name} · ${item.code}`,
  })),
]);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [pairData, jobData, employeeData] = await Promise.all([
      api.get<Paged<PreferencePair>>("/preference-pairs?page_size=200"),
      api.get<Paged<TrainingJob>>("/training-jobs?page_size=200"),
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
    ]);
    pairs.value = pairData.items;
    jobs.value = jobData.items;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

function collectPairs(): void {
  modal.openForm({
    title: "采集偏好对",
    sub: "从人工接管 diff、评估结果与反馈样本生成 chosen/rejected 对。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        options: employeeOptions.value,
      },
      {
        name: "sources",
        label: "来源",
        type: "multiselect",
        options: [
          { value: "intervention", label: "人工接管增量" },
          { value: "evaluation", label: "评估结果" },
          { value: "feedback", label: "人工反馈" },
        ],
        value: ["intervention", "evaluation", "feedback"],
        size: 3,
      },
      { name: "limit", label: "上限", type: "number", value: 200 },
    ],
    submitLabel: "开始采集",
    onSubmit: async (values) => {
      const result = await api.post<any>("/preference-pairs/collect", {
        employee_id: values.employee_id || null,
        sources: values.sources,
        limit: values.limit,
      });
      toast.push(`新增 ${result.created} 对，跳过 ${result.skipped} 对`);
      await load();
    },
  });
}

function exportPairs(): void {
  modal.openForm({
    title: "导出 DPO 数据集",
    sub: "导出为 JSONL，并标记为已导出；训练由外部 trainer 执行。",
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        options: employeeOptions.value,
      },
    ],
    submitLabel: "导出 JSONL",
    onSubmit: async (values) => {
      const result = await api.post<any>("/preference-pairs/export", {
        employee_id: values.employee_id || null,
      });
      lastExport.value = result.path;
      toast.push(`已导出 ${result.count} 对到 ${result.path}`);
      await load();
    },
  });
}

async function archivePair(row: PreferencePair): Promise<void> {
  try {
    await api.patch(`/preference-pairs/${row.id}/archive`, {});
    toast.push("偏好对已归档");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function createJob(): void {
  modal.openForm({
    title: "创建训练任务",
    sub: "平台记录数据集与训练台账；实际训练由外部 trainer 执行并通过状态接口回调。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        options: employeeOptions.value,
      },
      {
        name: "method",
        label: "方法",
        type: "select",
        options: [
          { value: "dpo", label: "DPO" },
          { value: "sft", label: "SFT" },
        ],
        value: "dpo",
      },
      {
        name: "dataset_path",
        label: "数据集路径",
        required: true,
        placeholder: "data/training/dpo_xxx.jsonl",
        value: lastExport.value,
      },
      { name: "config", label: "训练配置（JSON）", type: "json", value: { epochs: 1 } },
    ],
    submitLabel: "创建任务",
    onSubmit: async (values) => {
      await api.post("/training-jobs", {
        ...values,
        employee_id: values.employee_id || null,
      });
      toast.push("训练任务已创建");
      tab.value = "jobs";
      await load();
    },
  });
}

async function dispatchJob(row: TrainingJob): Promise<void> {
  if (!confirm(`确认把训练任务 #${row.id} 派发到外部 trainer？`)) return;
  try {
    const result = await api.post<any>(`/training-jobs/${row.id}/dispatch`, {});
    const external = result.metrics?.dispatch?.external_job_id;
    toast.push(external ? `已派发，外部任务 ${external}` : "已派发");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "派发失败", "error");
  }
}

function updateJob(row: TrainingJob): void {
  modal.openForm({
    title: `更新训练任务 #${row.id}`,
    sub: "供外部 trainer 回调；pending → running → succeeded/failed/cancelled。",
    wide: true,
    fields: [
      {
        name: "status",
        label: "状态",
        type: "select",
        options: ["running", "succeeded", "failed", "cancelled"],
        value: "running",
      },
      { name: "metrics", label: "指标（JSON）", type: "json", value: {} },
      { name: "error", label: "错误信息", type: "textarea", rows: 2 },
    ],
    submitLabel: "回调状态",
    onSubmit: async (values) => {
      await api.post(`/training-jobs/${row.id}/status`, {
        status: values.status,
        metrics: values.metrics || {},
        error: values.error || null,
      });
      toast.push("训练任务状态已更新");
      await load();
    },
  });
}

function primaryAction(): void {
  if (tab.value === "pairs") collectPairs();
  else createJob();
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="learning / dpo"
    title="训练数据"
    sub="把人工接管与评估差异变成 DPO 偏好数据，并记录训练任务。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="exportPairs">导出 JSONL</button>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="primaryAction">
        <AppIcon name="plus" />{{ tab === "pairs" ? "采集偏好对" : "创建训练任务" }}
      </button>
    </template>
  </PageHeader>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'pairs' }" @click="tab = 'pairs'">
      偏好对 <span class="dim">{{ pairs.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'jobs' }" @click="tab = 'jobs'">
      训练任务 <span class="dim">{{ jobs.length }}</span>
    </button>
  </div>

  <div class="panel">
    <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>

    <DataTable
      v-else-if="tab === 'pairs'"
      :rows="pairs"
      :columns="[
        {
          label: '偏好对',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.prompt).slice(0, 60) || '—'}</b><small>#${row.id} · ${esc(row.source_ref)}</small></div>`,
        },
        { label: '来源', format: (row) => `<span class='tag'>${esc(row.source_type)}</span>` },
        { label: '员工', format: (row) => esc(employeeMap[row.employee_id] || '—') },
        { label: '状态', key: 'status' },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有偏好对。先采集人工接管与评估差异。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button
            v-if="row.status !== 'archived'"
            class="btn btn-sm btn-danger"
            @click="archivePair(row)"
          >
            归档
          </button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else
      :rows="jobs"
      :columns="[
        {
          label: '任务',
          format: (row) =>
            `<div class='cell-main'><b>#${row.id} · ${esc(row.method)}</b><small class='mono'>${esc(row.dataset_path)}</small></div>`,
        },
        { label: '样本', format: (row) => `<span class='mono'>${row.dataset_size}</span>` },
        { label: '状态', key: 'status' },
        { label: '指标', format: (row) => `<span class='mono muted'>${JSON.stringify(row.metrics || {})}</span>` },
        { label: '员工', format: (row) => esc(employeeMap[row.employee_id] || '—') },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有训练任务。先导出数据集，再登记训练任务。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button
            v-if="row.status === 'pending'"
            class="btn btn-sm btn-primary"
            @click="dispatchJob(row)"
          >
            派发
          </button>
          <button class="btn btn-sm" @click="updateJob(row)">更新状态</button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
