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
import { esc, fmtDate } from "@/utils/format";

interface Tool {
  id: number;
  name: string;
  code: string;
  tool_type: string;
  description: string;
  risk_level: string;
  enabled: boolean;
  source: string;
  updated_at: string;
}

const rows = ref<Tool[]>([]);
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const data = await api.get<Paged<Tool>>("/tools?page_size=200");
    rows.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载工具失败", "error");
  }
}

function create(): void {
  modal.openForm({
    title: "创建工具",
    sub: "HTTP 工具配置 method/url/path；Python 工具配置 code。",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true },
      { name: "code", label: "编码", required: true, placeholder: "crm_get_user" },
      { name: "tool_type", label: "类型", type: "select", options: ["http", "python", "mcp"] },
      { name: "risk_level", label: "风险级别", type: "select", options: ["low", "medium", "high", "critical"] },
      { name: "description", label: "描述", full: true, type: "textarea", rows: 2 },
      {
        name: "parameters_schema",
        label: "参数 Schema",
        type: "json",
        full: true,
        value: { type: "object", properties: {} },
      },
      {
        name: "config",
        label: "工具配置",
        type: "json",
        full: true,
        value: { method: "GET", path: "/user/{{args.id}}", system_code: "self" },
      },
    ],
    submitLabel: "创建工具",
    onSubmit: async (values) => {
      await api.post("/tools", values);
      toast.push("工具已创建");
      await load();
    },
  });
}

onMounted(load);
</script>

<template>
  <PageHeader eyebrow="capabilities / tools" title="工具" sub="HTTP 接口、Python 沙箱与 MCP 工具。">
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="create"><AppIcon name="plus" />创建工具</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: '工具',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>`,
        },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.tool_type)}</span>` },
        { label: '来源', format: (row) => `<span class='muted'>${esc(row.source)}</span>` },
        { label: '风险', key: 'risk' },
        { label: '状态', key: 'status' },
        { label: '更新', format: (row) => `<span class='muted'>${fmtDate(row.updated_at)}</span>` },
      ]"
      empty-text="还没有工具"
    >
      <template #cell-risk="{ row }">
        <StatusPill :status="row.risk_level" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.enabled ? 'active' : 'disabled'" />
      </template>
    </DataTable>
  </div>
</template>
