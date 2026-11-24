<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";

interface AgentEmployee {
  id: number;
  name: string;
  code: string;
  position?: string | null;
  status: string;
  model_name?: string;
  avatar?: string | null;
  created_at?: string;
}

const props = defineProps<{ agent: any }>();

const drawer = useDrawerStore();
const toast = useToastStore();
const router = useRouter();

const rows = ref<AgentEmployee[]>([]);
const total = ref(0);
const loading = ref(true);
const error = ref("");

const activeCount = computed(
  () => rows.value.filter((item) => item.status === "active").length,
);

const statusText: Record<string, string> = {
  active: "在岗",
  draft: "草稿",
  disabled: "停用",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const data = await api.get<Paged<AgentEmployee>>(
      `/agents/${props.agent.id}/employees?page_size=200`,
    );
    rows.value = data.items;
    total.value = data.total;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载使用方失败";
  } finally {
    loading.value = false;
  }
}

function openWorkbench(employee: AgentEmployee): void {
  drawer.close();
  void router.push({ name: "employees", query: { employee: String(employee.id) } });
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ agent.name }} · 使用方</h3>
      <p class="mono">{{ agent.code }} · 绑定该 Agent 的数字员工</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="agent-summary">
    <div class="summary-item">
      <span>模型</span>
      <b class="mono">{{ agent.model_name || "默认模型" }}</b>
    </div>
    <div class="summary-item">
      <span>工具</span>
      <b class="mono">{{ (agent.tools || []).length }}</b>
    </div>
    <div class="summary-item">
      <span>使用员工</span>
      <b class="mono">{{ total }}</b>
    </div>
    <div class="summary-item">
      <span>其中在岗</span>
      <b class="mono">{{ activeCount }}</b>
    </div>
  </div>

  <div v-if="loading" class="muted drawer-hint">加载中…</div>

  <div v-else-if="error" class="drawer-error">
    <p>{{ error }}</p>
    <button class="btn btn-sm" type="button" @click="load">重试</button>
  </div>

  <div v-else-if="!rows.length" class="drawer-empty">
    <p>还没有数字员工绑定该 Agent。</p>
    <p class="muted">
      前往「数字员工 → 新增员工」，在绑定 Agent 步骤中选择
      <b>{{ agent.name }}</b>。
    </p>
  </div>

  <div v-else class="employee-list">
    <button
      v-for="employee in rows"
      :key="employee.id"
      type="button"
      class="employee-row"
      @click="openWorkbench(employee)"
    >
      <span class="avatar">{{ (employee.name || "员").slice(0, 1) }}</span>
      <span class="employee-main">
        <b>{{ employee.name }}</b>
        <small class="mono">{{ employee.code }}</small>
      </span>
      <span class="employee-meta">
        <span class="muted">{{ employee.position || "未设置岗位" }}</span>
        <span class="mono muted">{{ employee.model_name || agent.model_name || "默认模型" }}</span>
      </span>
      <StatusPill :status="employee.status" :text="statusText[employee.status] || employee.status" />
      <span class="open-hint">打开工作台 <AppIcon name="arrow" /></span>
    </button>
  </div>
</template>

<style scoped>
.agent-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
}
.summary-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.summary-item span {
  font-size: 10px;
  color: var(--dim);
}
.summary-item b {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.drawer-hint {
  padding: 20px 0;
  font-size: 12px;
}
.drawer-error {
  border: 1px solid color-mix(in srgb, var(--coral) 40%, var(--line));
  border-radius: 10px;
  padding: 14px;
  font-size: 12px;
  color: var(--coral);
}
.drawer-error p {
  margin: 0 0 10px;
}
.drawer-empty {
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  padding: 18px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text);
}
.drawer-empty p {
  margin: 0;
}
.drawer-empty p.muted {
  margin-top: 6px;
  color: var(--dim);
}
.employee-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.employee-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1.3fr) minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.employee-row:hover {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 7%, var(--panel-2));
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
  font-size: 13px;
}
.employee-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.employee-main b {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.employee-main small,
.employee-meta {
  font-size: 10.5px;
  color: var(--dim);
}
.employee-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.employee-meta span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.open-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: var(--dim);
  white-space: nowrap;
}
.open-hint :deep(svg) {
  width: 12px;
  height: 12px;
}
@media (max-width: 720px) {
  .agent-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .employee-row {
    grid-template-columns: 34px minmax(0, 1fr) auto;
  }
  .employee-meta,
  .open-hint {
    display: none;
  }
}
</style>
