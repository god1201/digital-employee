<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface JobTemplate {
  id: number;
  code: string;
  name: string;
  category: string;
  description: string;
  role_code: string;
  skill_codes: string[];
  tool_codes: string[];
  knowledge_base_ids: number[];
  persona: Record<string, any>;
  contract: Record<string, any>;
  eval_suite_code?: string | null;
  is_builtin: boolean;
}

const templates = ref<JobTemplate[]>([]);
const employees = ref<Employee[]>([]);
const loading = ref(false);
const keyword = ref("");

const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [templateData, employeeData] = await Promise.all([
      api.get<JobTemplate[]>("/job-templates"),
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
    ]);
    templates.value = templateData;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

function apply(template: JobTemplate): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: `应用岗位模板 · ${template.name}`,
    sub: "会装配技能、人设，并生成岗位契约草稿；不会直接生效。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "应用到员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      {
        name: "install_skills",
        label: "装配技能",
        type: "select",
        options: [
          { value: "true", label: "是（自动解析依赖）" },
          { value: "false", label: "否" },
        ],
        value: "true",
      },
      {
        name: "upsert_persona",
        label: "写入人设",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
        value: "true",
      },
      {
        name: "create_contract_draft",
        label: "生成契约草稿",
        type: "select",
        options: [
          { value: "true", label: "是（需人工确认）" },
          { value: "false", label: "否" },
        ],
        value: "true",
      },
    ],
    submitLabel: "应用模板",
    onSubmit: async (values) => {
      const result = await api.post<any>(
        `/digital-employees/${values.employee_id}/apply-job-template`,
        {
          template_code: template.code,
          install_skills: String(values.install_skills) === "true",
          upsert_persona: String(values.upsert_persona) === "true",
          create_contract_draft: String(values.create_contract_draft) === "true",
        },
      );
      toast.push(
        `已装配技能 ${result.skills.installed.length} 个，跳过 ${result.skills.skipped.length} 个`,
      );
      if (result.skills.conflicts?.length) {
        toast.push(`技能冲突：${result.skills.conflicts.join("；")}`, "error");
      }
      for (const note of result.notes || []) toast.push(note, "info");
    },
  });
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="workforce / job templates"
    title="岗位模板"
    sub="技能 + 工具 + 知识库 + 人设 + 评估集的岗位五件套。"
  >
    <template #actions>
      <input v-model="keyword" class="filter-input" placeholder="搜索岗位 / 技能" />
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
    </template>
  </PageHeader>

  <div class="panel">
    <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>
    <DataTable
      v-else
      :rows="
        templates.filter(
          (item) =>
            !keyword ||
            `${item.name} ${item.code} ${item.skill_codes.join(' ')}`.includes(keyword),
        )
      "
      :columns="[
        {
          label: '岗位模板',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)} · ${esc(row.category)}</small></div>`,
        },
        { label: '说明', format: (row) => esc(row.description) },
        {
          label: '技能',
          format: (row) => `<span class='mono muted'>${(row.skill_codes || []).join(', ')}</span>`,
        },
        {
          label: '工具',
          format: (row) => `<span class='mono muted'>${(row.tool_codes || []).join(', ')}</span>`,
        },
        {
          label: '人设',
          format: (row) => `<span class='tag'>${esc(row.persona?.tone || '—')}</span>`,
        },
        { label: '来源', format: (row) => `<span class='tag'>${row.is_builtin ? '内置' : '自定义'}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有岗位模板。重启后端会自动写入内置模板。"
    >
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-primary" @click="apply(row)">应用</button>
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
