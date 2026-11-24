<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api/client";
import ChatDrawer from "@/components/ChatDrawer.vue";
import GroupChatModal from "@/components/GroupChatModal.vue";
import AppIcon from "@/components/AppIcon.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useEmployeeStore } from "@/stores/employee";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";

const employeeStore = useEmployeeStore();
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const router = useRouter();
const busy = ref(false);

const employee = computed(() => employeeStore.selected);
const summary = computed(() => employeeStore.summary);
const statusLabel = computed(() => {
  const value = summary.value?.status;
  if (value === "working") return "工作中";
  if (value === "waiting") return "等待确认";
  if (value === "offline") return "已停用";
  return "空闲";
});
const todayTokens = computed(
  () => summary.value?.token_summary?.today ?? 0,
);
const currentTask = computed(
  () => summary.value?.current_task?.title || "",
);

async function refreshSummary(): Promise<void> {
  if (!employee.value) return;
  try {
    const data = await api.get<any>(
      `/digital-employees/${employee.value.id}/workbench`,
    );
    employeeStore.updateSummary(data);
  } catch {
    // 员工坞静默失败，不打断主流程
  }
}

function openChat(): void {
  if (!employee.value) return;
  drawer.open(ChatDrawer, { employee: employee.value });
}

function openWorkbench(): void {
  if (!employee.value) return;
  router.push({
    path: "/employees",
    query: { employee: String(employee.value.id) },
  });
}

async function openGroupChat(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  try {
    const data = await api.get<any>("/digital-employees?page_size=200");
    modal.openCustom(GroupChatModal, {
      employees: data.items,
      onCreate: async (payload: { title: string; employee_ids: number[] }) => {
        try {
          const result = await api.post<any>("/conversations", {
            mode: "group",
            title: payload.title,
            employee_ids: payload.employee_ids,
          });
          drawer.open(ChatDrawer, {
            conversationId: result.conversation.id,
            employee: null,
          });
          toast.push("群聊已创建");
        } catch (err) {
          toast.push(err instanceof Error ? err.message : "创建群聊失败", "error");
        }
      },
    });
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载员工失败", "error");
  } finally {
    busy.value = false;
  }
}

onMounted(refreshSummary);
watch(() => employee.value?.id, refreshSummary);
</script>

<template>
  <div class="employee-dock" :class="{ active: !!employee }">
    <template v-if="employee">
      <div class="dock-head">
        <span class="dock-avatar">{{ (employee.name || "E").slice(0, 1) }}</span>
        <div class="dock-identity">
          <b>{{ employee.name }}</b>
          <small>{{ employee.position || "未设置岗位" }}</small>
        </div>
        <span class="dock-status" :class="summary?.status || 'idle'">
          {{ statusLabel }}
        </span>
      </div>
      <div class="dock-body">
        <div class="dock-line">
          <span>当前</span>
          <b>{{ currentTask || "暂无进行中的任务" }}</b>
        </div>
        <div class="dock-line">
          <span>今日</span>
          <b class="mono">{{ todayTokens }} tokens</b>
        </div>
      </div>
      <div class="dock-actions">
        <button class="btn btn-sm btn-primary" @click="openChat">
          <AppIcon name="spark" />去对话
        </button>
        <button class="btn btn-sm btn-ghost" :disabled="busy" @click="openGroupChat">
          <AppIcon name="users" />拉群
        </button>
        <button class="btn btn-sm btn-ghost" @click="openWorkbench">
          <AppIcon name="grid" />工作台
        </button>
      </div>
    </template>
    <template v-else>
      <div class="dock-empty">
        <AppIcon name="users" />
        <div>
          <b>选择一个数字员工</b>
          <small>查看状态、工作、Token，并直接对话。</small>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.employee-dock {
  margin: 10px 10px 8px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-2);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.employee-dock.active {
  border-color: color-mix(in srgb, var(--amber) 35%, var(--line));
}
.dock-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dock-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.16);
  color: var(--amber);
  font-size: 11px;
  font-weight: 700;
  flex: 0 0 auto;
}
.dock-identity {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.dock-identity b {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dock-identity small {
  font-size: 9.5px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dock-status {
  font-size: 9px;
  border-radius: 999px;
  padding: 2px 6px;
  border: 1px solid var(--line);
  color: var(--dim);
  white-space: nowrap;
}
.dock-status.working {
  color: #4fd1b0;
  border-color: rgba(79, 209, 176, 0.4);
}
.dock-status.waiting {
  color: var(--amber);
  border-color: rgba(232, 163, 61, 0.4);
}
.dock-status.offline {
  color: var(--coral);
  border-color: rgba(239, 106, 91, 0.4);
}
.dock-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 10px;
}
.dock-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.dock-line span {
  color: var(--dim);
  flex: 0 0 auto;
}
.dock-line b {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: right;
}
.dock-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.dock-actions .btn {
  flex: 1;
  min-width: 0;
  padding: 0 6px;
  font-size: 10px;
}
.dock-actions :deep(svg) {
  width: 12px;
  height: 12px;
}
.dock-empty {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--dim);
}
.dock-empty :deep(svg) {
  width: 20px;
  height: 20px;
  color: var(--amber);
}
.dock-empty div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dock-empty b {
  font-size: 11px;
  color: var(--text);
}
.dock-empty small {
  font-size: 9.5px;
  line-height: 1.4;
}
</style>
