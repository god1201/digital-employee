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

interface AlertRule {
  id: number;
  name: string;
  metric: string;
  operator: string;
  threshold: number;
  window_minutes: number;
  enabled: boolean;
}

interface AlertEvent {
  id: number;
  rule_name: string;
  metric: string;
  message: string;
  value: number;
  threshold: number;
  operator: string;
  status: string;
  created_at: string;
}

interface EvaluationResult {
  triggered: boolean;
  value: number;
  event_id?: number | null;
  message?: string | null;
}

const rules = ref<AlertRule[]>([]);
const events = ref<AlertEvent[]>([]);
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [ruleData, eventData] = await Promise.all([
      api.get<Paged<AlertRule>>("/alert-rules?page_size=100").catch(() => null),
      api.get<Paged<AlertEvent>>("/alert-events?page_size=100").catch(() => null),
    ]);
    rules.value = ruleData?.items || [];
    events.value = eventData?.items || [];
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载告警数据失败", "error");
  }
}

function createRule(): void {
  modal.openForm({
    title: "新建告警规则",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true, placeholder: "失败率告警" },
      {
        name: "metric",
        label: "指标",
        type: "select",
        options: [
          "failure_rate",
          "queue_backlog",
          "avg_duration_ms",
          "token_usage",
          "token_cost",
          "human_intervention_rate",
          "sensitive_actions",
        ],
      },
      { name: "operator", label: "比较符", type: "select", options: ["gt", "gte", "lt", "lte"] },
      { name: "threshold", label: "阈值", type: "number", value: 0.2, step: "0.01" },
      { name: "window_minutes", label: "窗口（分钟）", type: "number", value: 60 },
      { name: "cooldown_minutes", label: "冷却（分钟）", type: "number", value: 30 },
      { name: "webhook_url", label: "Webhook URL", full: true, placeholder: "https://example.com/hooks/alert" },
      {
        name: "enabled",
        label: "启用",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
      },
    ],
    submitLabel: "创建规则",
    onSubmit: async (values) => {
      await api.post("/alert-rules", {
        name: values.name,
        metric: values.metric,
        operator: values.operator,
        threshold: Number(values.threshold),
        window_minutes: Number(values.window_minutes),
        cooldown_minutes: Number(values.cooldown_minutes),
        webhook_url: values.webhook_url || null,
        enabled: values.enabled === "true",
      });
      toast.push("告警规则已创建");
      await load();
    },
  });
}

async function evaluate(row: AlertRule): Promise<void> {
  try {
    const result = await api.post<EvaluationResult>(`/alert-rules/${row.id}/evaluate`, {});
    toast.push(
      result.triggered ? `已触发，值 ${Number(result.value).toFixed(4)}` : "未触发",
      result.triggered ? "success" : "info",
    );
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "评估失败", "error");
  }
}

async function acknowledge(row: AlertEvent): Promise<void> {
  try {
    await api.post(`/alert-events/${row.id}/ack`, {});
    toast.push("告警已确认");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "确认失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="governance / alerts"
    title="告警"
    sub="失败率、积压、耗时、成本与敏感操作的阈值告警。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="createRule"><AppIcon name="plus" />新建规则</button>
    </template>
  </PageHeader>

  <div class="grid-equal">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">规则</div>
          <div class="panel-sub">{{ rules.length }} 条</div>
        </div>
      </div>
      <DataTable
        :rows="rules"
        :columns="[
          {
            label: '规则',
            format: (row) =>
              `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(row.metric)} ${esc(row.operator)} ${esc(row.threshold)}</small></div>`,
          },
          { label: '窗口', format: (row) => `<span class='mono'>${row.window_minutes}m</span>` },
          { label: '状态', key: 'status' },
          { label: '', key: 'actions' },
        ]"
        empty-text="还没有告警规则"
      >
        <template #cell-status="{ row }">
          <StatusPill :status="row.enabled ? 'active' : 'disabled'" />
        </template>
        <template #cell-actions="{ row }">
          <button class="btn btn-sm" @click="evaluate(row)">评估</button>
        </template>
      </DataTable>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">事件</div>
          <div class="panel-sub">最近 {{ events.length }} 条</div>
        </div>
      </div>
      <DataTable
        :rows="events"
        :columns="[
          {
            label: '事件',
            format: (row) =>
              `<div class='cell-main'><b>${esc(row.rule_name)}</b><small>${esc(row.message)}</small></div>`,
          },
          { label: '值', format: (row) => `<span class='mono'>${Number(row.value).toFixed(4)}</span>` },
          { label: '状态', key: 'status' },
          { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
          { label: '', key: 'actions' },
        ]"
        empty-text="还没有告警事件"
      >
        <template #cell-status="{ row }">
          <StatusPill :status="row.status" />
        </template>
        <template #cell-actions="{ row }">
          <button v-if="row.status === 'open'" class="btn btn-sm" @click="acknowledge(row)">确认</button>
        </template>
      </DataTable>
    </div>
  </div>
</template>
