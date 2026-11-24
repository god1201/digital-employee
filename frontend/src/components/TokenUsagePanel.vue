<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ employeeId: number }>();
const toast = useToastStore();

const data = ref<any>(null);
const loading = ref(false);
const error = ref("");
const exporting = ref(false);
const source = ref<"all" | "task" | "chat">("all");
const projectId = ref("");
const toolCode = ref("");

const sourceTabs = [
  { key: "all" as const, label: "全部" },
  { key: "task" as const, label: "任务" },
  { key: "chat" as const, label: "对话" },
];

const events = computed(() => data.value?.events || []);
const filteredTotal = computed(
  () => data.value?.filtered_total ?? events.value.length,
);
const projectOptions = computed(() => data.value?.project_options || []);
const toolOptions = computed(() => data.value?.tool_options || []);
const hasFilters = computed(
  () =>
    source.value !== "all" || !!projectId.value || !!toolCode.value,
);

const days = computed(() =>
  (data.value?.by_day || []).slice(-14).map((item: any) => ({
    ...item,
    label: String(item.date).slice(5),
  })),
);
const maxDayTokens = computed(() =>
  Math.max(1, ...days.value.map((item: any) => item.tokens)),
);

const totalTokens = computed(() => data.value?.total_tokens ?? 0);
const totalCost = computed(() => data.value?.total_cost ?? 0);
const taskTokens = computed(() => data.value?.by_source?.task ?? 0);
const chatTokens = computed(() => data.value?.by_source?.chat ?? 0);
const topTool = computed(() => {
  const entries = Object.entries(data.value?.by_tool || {});
  return entries.length ? entries[0] : null;
});

function tokenText(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function queryParams(): string {
  const params = new URLSearchParams({ days: "30" });
  if (source.value !== "all") params.set("source", source.value);
  if (projectId.value) params.set("project_id", projectId.value);
  if (toolCode.value) params.set("tool_code", toolCode.value);
  return params.toString();
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.get<any>(
      `/digital-employees/${props.employeeId}/token-usage?${queryParams()}`,
    );
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载 Token 明细失败";
  } finally {
    loading.value = false;
  }
}

function resetFilters(): void {
  source.value = "all";
  projectId.value = "";
  toolCode.value = "";
}

async function exportCsv(): Promise<void> {
  exporting.value = true;
  try {
    await api.download(
      `/digital-employees/${props.employeeId}/token-usage/export?${queryParams()}`,
      `token-usage-${props.employeeId}.csv`,
    );
    toast.push("Token 明细已导出");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "导出失败", "error");
  } finally {
    exporting.value = false;
  }
}

onMounted(load);
watch([source, projectId, toolCode], load);
watch(() => props.employeeId, load);
</script>

<template>
  <div class="token-panel">
    <div v-if="loading" class="muted token-loading">加载 Token 明细…</div>
    <div v-else-if="error" class="token-error">
      {{ error }}
      <button class="btn btn-sm btn-ghost" @click="load">
        <AppIcon name="refresh" />重试
      </button>
    </div>
    <template v-else-if="data">
      <div class="token-toolbar">
        <div class="source-tabs">
          <button
            v-for="item in sourceTabs"
            :key="item.key"
            class="source-tab"
            :class="{ active: source === item.key }"
            @click="source = item.key"
          >
            {{ item.label }}
          </button>
        </div>
        <select v-model="projectId" class="token-select" title="按项目筛选">
          <option value="">全部项目</option>
          <option
            v-for="project in projectOptions"
            :key="project.id"
            :value="String(project.id)"
          >
            {{ project.name || `项目 #${project.id}` }}
          </option>
        </select>
        <select v-model="toolCode" class="token-select" title="按工具筛选">
          <option value="">全部工具</option>
          <option v-for="code in toolOptions" :key="code" :value="code">
            {{ code }}
          </option>
        </select>
        <button
          v-if="hasFilters"
          class="btn btn-sm btn-ghost"
          type="button"
          @click="resetFilters"
        >
          重置
        </button>
        <span class="spacer" />
        <button
          class="btn btn-sm"
          type="button"
          :disabled="exporting || !filteredTotal"
          @click="exportCsv"
        >
          <AppIcon name="arrow" />{{ exporting ? "导出中…" : "导出 CSV" }}
        </button>
      </div>

      <div class="token-cards">
        <div class="token-card">
          <span>近 30 天 Token</span>
          <b>{{ tokenText(totalTokens) }}</b>
          <small class="muted">成本 {{ totalCost.toFixed(4) }}</small>
        </div>
        <div class="token-card">
          <span>任务步骤</span>
          <b>{{ tokenText(taskTokens) }}</b>
          <small class="muted">执行与工具</small>
        </div>
        <div class="token-card">
          <span>对话回复</span>
          <b>{{ tokenText(chatTokens) }}</b>
          <small class="muted">直接对话与群聊</small>
        </div>
        <div class="token-card">
          <span>最高工具消耗</span>
          <b class="mono">{{ topTool?.[0] || "—" }}</b>
          <small class="muted">
            {{ topTool ? `${tokenText(Number(topTool[1]))} tokens` : "暂无工具消耗" }}
          </small>
        </div>
      </div>

      <div class="section-label">按天消耗</div>
      <div v-if="days.length" class="day-chart">
        <div v-for="day in days" :key="day.date" class="day-bar">
          <div class="bar-track">
            <div
              class="bar-fill"
              :style="{ height: `${Math.max(4, (day.tokens / maxDayTokens) * 100)}%` }"
              :title="`${day.date} · ${day.tokens} tokens`"
            />
          </div>
          <span>{{ day.label }}</span>
          <small>{{ tokenText(day.tokens) }}</small>
        </div>
      </div>
      <div v-else class="muted" style="font-size: 12px">暂无消耗</div>

      <div class="section-label detail-head">
        <span>消耗明细</span>
        <span class="muted">共 {{ filteredTotal }} 条{{ hasFilters ? "（已筛选）" : "" }}</span>
      </div>

      <div v-if="events.length" class="table-wrap token-table">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>来源</th>
              <th>场景</th>
              <th>项目</th>
              <th>动作</th>
              <th>工具</th>
              <th>模型</th>
              <th>Token</th>
              <th>成本</th>
              <th>Trace</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(event, index) in events" :key="index">
              <td class="muted">{{ fmtDate(event.occurred_at) }}</td>
              <td><span class="tag">{{ event.source }}</span></td>
              <td class="ellipsis" :title="event.context_title || ''">
                {{ event.context_title || "—" }}
              </td>
              <td class="ellipsis" :title="event.project_name || ''">
                {{ event.project_name || "—" }}
              </td>
              <td>
                {{ event.action }}
                <small class="muted"> · {{ event.action_type }}</small>
              </td>
              <td class="mono">{{ event.tool_code || "—" }}</td>
              <td class="mono">{{ event.model || "—" }}</td>
              <td class="mono">{{ event.tokens }}</td>
              <td class="mono">{{ Number(event.cost).toFixed(4) }}</td>
              <td class="mono trace" :title="event.trace_id || ''">
                {{ event.trace_id ? String(event.trace_id).slice(0, 10) : "—" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12px; padding: 12px 0">
        暂无符合条件的消耗明细
      </div>
    </template>
  </div>
</template>

<style scoped>
.token-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.token-loading {
  padding: 24px 0;
}
.token-error {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--coral);
  font-size: 12px;
}
.token-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}
.token-select {
  height: 27px;
  max-width: 170px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-2);
  color: var(--text);
  font-size: 10.5px;
  padding: 0 6px;
  outline: none;
}
.spacer {
  flex: 1;
}
.token-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.token-card {
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.token-card span {
  font-size: 10.5px;
  color: var(--dim);
}
.token-card b {
  font-size: 17px;
  font-family: var(--mono);
}
.token-card small {
  font-size: 10px;
}
.day-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 140px;
  padding: 4px 4px 0;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
}
.day-bar {
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  min-width: 0;
}
.bar-track {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.bar-fill {
  width: 70%;
  max-width: 26px;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, var(--amber), rgba(232, 163, 61, 0.25));
  min-height: 4px;
}
.day-bar span,
.day-bar small {
  font-size: 9px;
  color: var(--dim);
  white-space: nowrap;
}
.source-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
}
.source-tab {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--dim);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}
.source-tab.active {
  border-color: var(--amber);
  color: var(--amber);
  background: rgba(232, 163, 61, 0.08);
}
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.detail-head .muted {
  font-size: 10px;
  letter-spacing: 0;
  text-transform: none;
}
.token-table {
  max-height: 360px;
  overflow: auto;
}
.token-table table {
  min-width: 980px;
}
.token-table td,
.token-table th {
  white-space: nowrap;
}
.token-table .ellipsis {
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.trace {
  color: var(--dim);
  font-size: 10px;
  white-space: nowrap;
}
</style>
