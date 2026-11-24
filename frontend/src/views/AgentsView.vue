<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AgentCreateWizard from "@/components/AgentCreateWizard.vue";
import AgentEmployeesDrawer from "@/components/AgentEmployeesDrawer.vue";
import AgentResultDrawer from "@/components/AgentResultDrawer.vue";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc } from "@/utils/format";
import type { Paged } from "@/api/types";

interface Agent {
  id: number;
  name: string;
  code: string;
  agent_type: string;
  protocol: string;
  status: string;
  description?: string;
  model_name?: string;
  tools: string[];
  capabilities?: string[];
  employee_count?: number;
  active_employee_count?: number;
  employee_names?: string[];
}

interface AgentInvokeResult {
  agent_id: number;
  agent_code: string;
  output: unknown;
  tokens: number;
  latency_ms: number;
  tool_calls: unknown[];
}

const rows = ref<Agent[]>([]);
const tools = ref<any[]>([]);
const showInactive = ref(false);
const loading = ref(false);
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

async function load(): Promise<void> {
  loading.value = true;
  try {
    const statusQuery = showInactive.value ? "" : "&status=active";
    const [agentData, toolData] = await Promise.all([
      api.get<Paged<Agent>>(`/agents?page_size=200${statusQuery}`),
      api.get<Paged<any>>("/tools?page_size=200&enabled=true"),
    ]);
    rows.value = agentData.items;
    tools.value = toolData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载 Agent 失败", "error");
  } finally {
    loading.value = false;
  }
}

function usageText(agent: Agent): string {
  const count = agent.active_employee_count ?? 0;
  const total = agent.employee_count ?? 0;
  if (!total) return "未被使用";
  const names = agent.employee_names || [];
  const suffix = total > names.length ? "…" : "";
  const base = `${count} 人在岗 · ${names.slice(0, 3).join("、")}${suffix}`;
  return total > count ? `${base}（共 ${total} 个）` : base;
}

function openUsage(agent: Agent): void {
  drawer.open(AgentEmployeesDrawer, { agent });
}

function toggleInactive(): void {
  showInactive.value = !showInactive.value;
  void load();
}

function create(): void {
  modal.openCustom(AgentCreateWizard, {
    tools: tools.value,
    onCreated: async () => {
      toast.push("Agent 已注册");
      await load();
    },
  });
}

function invoke(row: Agent): void {
  modal.openForm({
    title: "调用 Agent",
    sub: "用于调试 Agent 的输入输出与工具调用。",
    wide: true,
    fields: [
      { name: "input", label: "输入 JSON", type: "json", full: true, value: { text: "hello" } },
      { name: "prompt", label: "Prompt（可选）", type: "textarea", full: true, rows: 3 },
    ],
    submitLabel: "开始调用",
    onSubmit: async (values) => {
      const result = await api.post<AgentInvokeResult>(`/agents/${row.id}/invoke`, values);
      drawer.open(AgentResultDrawer, { result, agentName: row.name });
    },
  });
}

async function disable(row: Agent): Promise<void> {
  if (!window.confirm("确认停用该 Agent？已绑定的数字员工将无法继续调用。")) return;
  try {
    await api.delete(`/agents/${row.id}`);
    toast.push("Agent 已停用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "停用失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="capabilities / agents"
    title="Agent"
    sub="可复用能力单元：先配置模型、工具与提示词，再绑定给数字员工。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-ghost" @click="toggleInactive">
        {{ showInactive ? "隐藏停用" : "显示停用" }}
      </button>
      <button class="btn btn-primary" @click="create"><AppIcon name="plus" />新建 Agent</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: 'Agent',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>`,
        },
        {
          label: '模型',
          format: (row) => `<span class='mono'>${esc(row.model_name || '默认模型')}</span>`,
        },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.agent_type)}</span>` },
        { label: '工具', format: (row) => `<span class='mono'>${(row.tools || []).length}</span>` },
        {
          label: '能力',
          format: (row) => `<span class='mono'>${(row.capabilities || []).length}</span>`,
        },
        { label: '使用员工', key: 'usage' },
        { label: '状态', key: 'status' },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有 Agent。点击右上角「新建 Agent」开始配置。"
    >
      <template #cell-usage="{ row }">
        <button
          type="button"
          class="usage-link"
          :class="{ unused: !row.employee_count }"
          @click="openUsage(row)"
        >
          {{ usageText(row) }}
        </button>
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openUsage(row)">使用方</button>
          <button class="btn btn-sm" @click="invoke(row)">调用</button>
          <button
            v-if="row.status !== 'disabled'"
            class="btn btn-sm btn-danger"
            @click="disable(row)"
          >
            停用
          </button>
        </div>
      </template>
    </DataTable>
    <div v-if="loading" class="loading-hint muted">加载中…</div>
  </div>
</template>

<style scoped>
.usage-link {
  border: none;
  background: transparent;
  padding: 0;
  text-align: left;
  font-size: 11px;
  color: var(--text);
  cursor: pointer;
  text-decoration: underline dotted color-mix(in srgb, var(--amber) 60%, transparent);
  text-underline-offset: 3px;
}
.usage-link:hover {
  color: var(--amber);
}
.usage-link.unused {
  color: var(--dim);
  text-decoration: none;
}
.loading-hint {
  padding: 12px 4px 0;
  font-size: 11px;
}
</style>
