<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc } from "@/utils/format";

interface ApiRegistry {
  id: number;
  name: string;
  method: string;
  path: string;
  system_code: string;
  system_name: string;
  risk_level: string;
  source: string;
}

interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
}

interface ToToolResult {
  tool_id: number;
  code: string;
  created: boolean;
}

const rows = ref<ApiRegistry[]>([]);
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const data = await api.get<Paged<ApiRegistry>>("/api-registries?page_size=200");
    rows.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载接口目录失败", "error");
  }
}

function importOpenApi(): void {
  modal.openForm({
    title: "导入 OpenAPI",
    sub: "粘贴 OpenAPI 3.x / Swagger JSON，自动生成接口目录。",
    wide: true,
    fields: [
      { name: "system_name", label: "系统名称", required: true, placeholder: "CRM" },
      { name: "system_code", label: "系统编码", required: true, placeholder: "crm" },
      {
        name: "overwrite",
        label: "覆盖已有",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
      },
      { name: "spec", label: "OpenAPI JSON", type: "json", full: true, value: { openapi: "3.0.0", paths: {} } },
    ],
    submitLabel: "导入",
    onSubmit: async (values) => {
      const result = await api.post<ImportResult>("/api-registries/import-openapi", {
        system_name: values.system_name,
        system_code: values.system_code,
        overwrite: values.overwrite === "true",
        spec: values.spec,
      });
      toast.push(`导入完成：新建 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`);
      await load();
    },
  });
}

async function toTool(row: ApiRegistry): Promise<void> {
  try {
    const result = await api.post<ToToolResult>(`/api-registries/${row.id}/to-tool`, {});
    toast.push(result.created ? `已生成工具 ${result.code}` : `工具已存在 ${result.code}`);
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "转换失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="capabilities / interfaces"
    title="接口登记"
    sub="企业 API 目录，支持 OpenAPI 导入与一键转工具。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="importOpenApi"><AppIcon name="plus" />导入 OpenAPI</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: '接口',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.path)}</small></div>`,
        },
        { label: '系统', format: (row) => `<span class='tag'>${esc(row.system_code)}</span>` },
        { label: '方法', format: (row) => `<span class='mono'>${esc(row.method)}</span>` },
        { label: '风险', key: 'risk' },
        { label: '来源', format: (row) => `<span class='muted'>${esc(row.source)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有登记接口"
    >
      <template #cell-risk="{ row }">
        <StatusPill :status="row.risk_level" />
      </template>
      <template #cell-actions="{ row }">
        <button class="btn btn-sm" @click="toTool(row)">转工具</button>
      </template>
    </DataTable>
  </div>
</template>
