<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import EmployeeContractDrawer from "@/components/EmployeeContractDrawer.vue";
import CapabilityMigrationDrawer from "@/components/CapabilityMigrationDrawer.vue";
import EmployeeOnboardingDrawer from "@/components/EmployeeOnboardingDrawer.vue";
import EmployeePersonaDrawer from "@/components/EmployeePersonaDrawer.vue";
import EmployeeProfileDrawer from "@/components/EmployeeProfileDrawer.vue";
import EmployeeSkillsDrawer from "@/components/EmployeeSkillsDrawer.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
  position?: string | null;
  status: string;
  model_provider: string;
  model_name: string;
  created_at: string;
}

const rows = ref<Employee[]>([]);
const loading = ref(false);
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await api.get<Paged<Employee>>("/digital-employees?page_size=200");
    rows.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

function create(): void {
  modal.openForm({
    title: "新增数字员工",
    sub: "创建岗位身份并绑定模型与提示词。",
    fields: [
      { name: "name", label: "姓名", required: true, placeholder: "例如：内容审核员" },
      { name: "code", label: "编码", required: true, placeholder: "reviewer_01" },
      { name: "position", label: "岗位", placeholder: "内容审核" },
      {
        name: "status",
        label: "状态",
        type: "select",
        options: ["draft", "active", "disabled"],
        value: "active",
      },
      { name: "model_provider", label: "模型供应商", value: "openai" },
      { name: "model_name", label: "模型名称", placeholder: "gpt-4o-mini" },
      { name: "description", label: "岗位职责", type: "textarea", rows: 3 },
      { name: "system_prompt", label: "系统提示词", type: "textarea", rows: 4 },
    ],
    submitLabel: "创建员工",
    onSubmit: async (values) => {
      await api.post("/digital-employees", values);
      toast.push("员工已创建");
      await load();
    },
  });
}

function openContract(row: Employee): void {
  drawer.open(EmployeeContractDrawer, { employee: row, onChanged: load });
}

function openProfile(row: Employee): void {
  drawer.open(EmployeeProfileDrawer, { employee: row });
}

function openSkills(row: Employee): void {
  drawer.open(EmployeeSkillsDrawer, { employee: row, onChanged: load });
}

function openMigration(row: Employee): void {
  drawer.open(CapabilityMigrationDrawer, { employee: row, onChanged: load });
}

function openPersona(row: Employee): void {
  drawer.open(EmployeePersonaDrawer, { employee: row, onChanged: load });
}

function openOnboarding(row: Employee): void {
  drawer.open(EmployeeOnboardingDrawer, { employee: row, onChanged: load });
}

async function disable(row: Employee): Promise<void> {
  if (!confirm(`确认停用数字员工「${row.name}」？`)) return;
  try {
    await api.delete(`/digital-employees/${row.id}`);
    toast.push("员工已停用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "停用失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="workforce / employees"
    title="数字员工"
    sub="岗位身份、模型配置与运行状态。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="create"><AppIcon name="plus" />新增员工</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: '员工',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(row.position || '未设置岗位')}</small></div>`,
        },
        { label: '编码', format: (row) => `<span class='mono'>${esc(row.code)}</span>` },
        { label: '状态', key: 'status' },
        { label: '模型', format: (row) => `<span class='mono'>${esc(row.model_name || row.model_provider)}</span>` },
        { label: '创建时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有数字员工，先创建一个岗位。"
    >
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openContract(row)">岗位契约</button>
          <button class="btn btn-sm" @click="openPersona(row)">人格风格</button>
          <button class="btn btn-sm" @click="openOnboarding(row)">入职引导</button>
          <button class="btn btn-sm" @click="openSkills(row)">技能装配</button>
          <button class="btn btn-sm" @click="openMigration(row)">能力迁移</button>
          <button class="btn btn-sm" @click="openProfile(row)">数字履历</button>
          <button class="btn btn-sm btn-danger" @click="disable(row)">停用</button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
