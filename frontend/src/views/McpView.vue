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

interface McpServer {
  id: number;
  name: string;
  code: string;
  transport: string;
  status: string;
  tool_count: number;
  last_connected_at?: string | null;
  last_error?: string | null;
}

interface McpSyncResult {
  tool_count: number;
  created: number;
  updated: number;
}

const rows = ref<McpServer[]>([]);
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const data = await api.get<Paged<McpServer>>("/mcp-servers?page_size=200");
    rows.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载 MCP Server 失败", "error");
  }
}

function create(): void {
  modal.openForm({
    title: "注册 MCP Server",
    sub: "stdio 需要 command 与 args；远程传输需要 url。",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true },
      { name: "code", label: "编码", required: true, placeholder: "demo_mcp" },
      { name: "transport", label: "传输", type: "select", options: ["stdio", "sse", "streamable_http"] },
      { name: "command", label: "命令", placeholder: "python" },
      { name: "args", label: "参数", type: "json", full: true, value: ["scripts/demo_mcp_server.py"] },
      { name: "env", label: "环境变量", type: "json", value: {} },
      { name: "url", label: "URL", placeholder: "https://mcp.example.com/mcp" },
      { name: "headers", label: "Headers", type: "json", full: true, value: {} },
      { name: "description", label: "描述", type: "textarea", full: true, rows: 2 },
    ],
    submitLabel: "注册",
    onSubmit: async (values) => {
      await api.post("/mcp-servers", values);
      toast.push("MCP Server 已注册");
      await load();
    },
  });
}

async function sync(row: McpServer): Promise<void> {
  try {
    const result = await api.post<McpSyncResult>(`/mcp-servers/${row.id}/sync`, {});
    toast.push(`同步完成：${result.tool_count} 个工具`);
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "同步失败", "error");
  }
}

async function disable(row: McpServer): Promise<void> {
  if (!window.confirm("确认停用该 MCP Server 及其工具？")) return;
  try {
    await api.delete(`/mcp-servers/${row.id}`);
    toast.push("MCP Server 已停用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "停用失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="capabilities / mcp"
    title="MCP"
    sub="stdio / SSE / Streamable HTTP 服务与工具同步。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="create"><AppIcon name="plus" />注册 MCP</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: '服务',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>`,
        },
        { label: '传输', format: (row) => `<span class='tag'>${esc(row.transport)}</span>` },
        { label: '工具', format: (row) => `<span class='mono'>${row.tool_count}</span>` },
        { label: '状态', key: 'status' },
        {
          label: '最近连接',
          format: (row) => `<span class='muted'>${fmtDate(row.last_connected_at)}</span>`,
        },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有 MCP Server"
    >
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="sync(row)">同步</button>
          <button class="btn btn-sm btn-danger" @click="disable(row)">停用</button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
