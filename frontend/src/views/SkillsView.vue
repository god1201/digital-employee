<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkillPackageDrawer from "@/components/SkillPackageDrawer.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface SkillPackage {
  id: number;
  code: string;
  name: string;
  category: string;
  description: string;
  version: number;
  status: string;
  is_builtin: boolean;
  algorithm: string;
  tool_codes: string[];
  dependencies: Array<{ code: string; min_version: number }>;
  conflicts_with: string[];
  permissions: Record<string, any>;
  tags: string[];
  created_at: string;
}

const rows = ref<SkillPackage[]>([]);
const employees = ref<Employee[]>([]);
const keyword = ref("");
const category = ref("");
const loading = ref(false);

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

const categories = [
  { value: "", label: "全部分类" },
  { value: "language", label: "语言类" },
  { value: "data", label: "数据类" },
  { value: "process", label: "流程类" },
  { value: "audit", label: "审核类" },
  { value: "learning", label: "学习类" },
];

const filtered = computed(() =>
  rows.value.filter((row) => {
    if (category.value && row.category !== category.value) return false;
    if (!keyword.value) return true;
    const haystack = `${row.name} ${row.code} ${row.description} ${(row.tags || []).join(" ")}`;
    return haystack.includes(keyword.value);
  }),
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [packageData, employeeData] = await Promise.all([
      api.get<Paged<SkillPackage>>("/skill-packages?page_size=200"),
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
    ]);
    rows.value = packageData.items;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

function lines(value: unknown): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseJson(value: string, label: string): Record<string, any> {
  try {
    const parsed = JSON.parse(value || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("必须是 JSON 对象");
    }
    return parsed;
  } catch {
    throw new Error(`「${label}」不是合法 JSON 对象`);
  }
}

function openDetail(row: SkillPackage): void {
  drawer.open(SkillPackageDrawer, { code: row.code, onChanged: load });
}

function depCodes(row: SkillPackage): string {
  return (row.dependencies || []).map((item) => item.code).join(", ") || "—";
}

function install(row: SkillPackage): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: `安装技能 · ${row.name}`,
    sub: `将自动解析依赖并提示权限并集。v${row.version} ${row.is_builtin ? "平台内置" : "自定义"}。`,
    fields: [
      {
        name: "employee_id",
        label: "安装到员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
    ],
    submitLabel: "安装",
    onSubmit: async (values) => {
      const result = await api.post<any>(
        `/digital-employees/${values.employee_id}/skills`,
        { code: row.code },
      );
      toast.push(`已安装 ${result.installed.length} 个技能（含依赖）`);
      for (const warning of result.warnings || []) toast.push(warning, "info");
    },
  });
}

function createPackage(): void {
  modal.openForm({
    title: "创建技能包",
    sub: "技能包 = 算法 + 工具权限 + 知识库 + 提示词 + 评估集；创建后为草稿，发布后进入市场。",
    wide: true,
    fields: [
      { name: "code", label: "编码", required: true, placeholder: "sales.followup" },
      { name: "name", label: "名称", required: true, placeholder: "销售跟进" },
      {
        name: "category",
        label: "分类",
        type: "select",
        options: [
          { value: "language", label: "语言类" },
          { value: "data", label: "数据类" },
          { value: "process", label: "流程类" },
          { value: "audit", label: "审核类" },
          { value: "learning", label: "学习类" },
        ],
        value: "language",
      },
      { name: "description", label: "描述", type: "textarea", rows: 2 },
      { name: "algorithm", label: "算法能力", placeholder: "NL2SQL / 规则比对 / RAG" },
      { name: "tool_codes", label: "工具编码（每行一个）", type: "textarea", rows: 2 },
      { name: "knowledge_base_ids", label: "知识库 ID（JSON）", type: "json", value: [] },
      { name: "prompt_template", label: "提示词", type: "textarea", rows: 3 },
      { name: "dependencies", label: "依赖（JSON）", type: "json", value: [] },
      { name: "conflicts_with", label: "冲突技能（每行一个）", type: "textarea", rows: 2 },
      {
        name: "permissions",
        label: "最小权限（JSON）",
        type: "json",
        value: { read_only: true, risk_level: "low", amount_threshold: null, data_scopes: [] },
      },
      { name: "common_combos", label: "常见组合（每行一个）", type: "textarea", rows: 2 },
      { name: "tags", label: "标签（每行一个）", type: "textarea", rows: 2 },
    ],
    submitLabel: "创建草稿",
    onSubmit: async (values) => {
      await api.post("/skill-packages", {
        code: values.code,
        name: values.name,
        category: values.category,
        description: values.description || "",
        algorithm: values.algorithm || "",
        tool_codes: lines(values.tool_codes),
        knowledge_base_ids: values.knowledge_base_ids || [],
        prompt_template: values.prompt_template || "",
        dependencies: values.dependencies || [],
        conflicts_with: lines(values.conflicts_with),
        permissions: parseJson(String(values.permissions), "最小权限"),
        common_combos: lines(values.common_combos),
        tags: lines(values.tags),
      });
      toast.push("技能包草稿已创建，发布后进入市场");
      await load();
    },
  });
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="skills / marketplace"
    title="技能市场"
    sub="可插拔技能包：依赖解析、冲突检测、权限并集与版本升级。"
  >
    <template #actions>
      <input v-model="keyword" class="filter-input" placeholder="搜索技能 / 标签" />
      <select v-model="category" class="filter-input">
        <option v-for="item in categories" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="createPackage"><AppIcon name="plus" />创建技能包</button>
    </template>
  </PageHeader>

  <div class="panel">
    <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>
    <DataTable
      v-else
      :rows="filtered"
      :columns="[
        {
          label: '技能',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)} · v${row.version}</small></div>`,
        },
        { label: '分类', format: (row) => `<span class='tag'>${esc(row.category)}</span>` },
        { label: '描述', format: (row) => esc(row.description || row.algorithm || '—') },
        {
          label: '权限',
          format: (row) =>
            `<span class='tag'>${row.permissions?.read_only ? '只读' : '可写'} · ${esc(row.permissions?.risk_level || 'low')}</span>`,
        },
        {
          label: '依赖',
          format: (row) => `<span class='mono muted'>${esc(depCodes(row))}</span>`,
        },
        { label: '来源', format: (row) => `<span class='tag'>${row.is_builtin ? '内置' : '自定义'}</span>` },
        { label: '状态', key: 'status' },
        { label: '', key: 'actions' },
      ]"
      empty-text="技能市场为空。先创建一个技能包草稿并发布。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openDetail(row)">详情</button>
          <button v-if="row.status === 'published'" class="btn btn-sm btn-primary" @click="install(row)">
            安装
          </button>
        </div>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.filter-input {
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
}
</style>
