<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface AuditLog {
  id: number;
  user_id?: number | null;
  employee_id?: number | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | number | null;
  detail?: Record<string, unknown> | null;
  ip_address?: string | null;
  created_at?: string | null;
}

const rows = ref<AuditLog[]>([]);
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const data = await api.get<Paged<AuditLog>>("/audit-logs?page_size=200");
    rows.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载审计日志失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="governance / audit"
    title="审计日志"
    sub="所有写操作与任务执行的动作留痕。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        { label: '时间', format: (row) => `<span class='muted mono'>${fmtDate(row.created_at)}</span>` },
        { label: '动作', format: (row) => `<span class='mono'>${esc(row.action)}</span>` },
        {
          label: '资源',
          format: (row) =>
            `<span class='muted'>${esc(row.resource_type || '—')} ${esc(row.resource_id || '')}</span>`,
        },
        { label: '员工', format: (row) => esc(row.employee_id || '—') },
        { label: 'IP', format: (row) => `<span class='mono dim'>${esc(row.ip_address || '—')}</span>` },
        { label: '详情', key: 'detail' },
      ]"
      empty-text="还没有审计日志"
    >
      <template #cell-detail="{ row }">
        <span class="truncate mono dim" :title="JSON.stringify(row.detail || {})">
          {{ JSON.stringify(row.detail || {}) }}
        </span>
      </template>
    </DataTable>
  </div>
</template>
