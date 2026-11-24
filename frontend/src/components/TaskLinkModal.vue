<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface TaskRow {
  id: number;
  title: string;
  status: string;
  task_type: string;
  employee_id?: number | null;
  project_id?: number | null;
  created_at: string;
}

const props = defineProps<{
  projectId: number;
  projectName?: string;
  employeeId?: number | null;
  onLinked?: () => void;
}>();

const modal = useModalStore();
const toast = useToastStore();

const rows = ref<TaskRow[]>([]);
const employeeNames = ref<Record<number, string>>({});
const loading = ref(true);
const error = ref("");
const keyword = ref("");
const linkingId = ref<number | null>(null);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return rows.value;
  return rows.value.filter((task) =>
    [task.title, task.task_type, employeeNames.value[task.employee_id || 0] || ""]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const employeeQuery = props.employeeId ? `&employee_id=${props.employeeId}` : "";
    const [taskData, employeeData] = await Promise.all([
      api.get<Paged<TaskRow>>(
        `/tasks/instances?page_size=200&unlinked=true${employeeQuery}`,
      ),
      api.get<Paged<any>>("/digital-employees?page_size=200"),
    ]);
    rows.value = taskData.items;
    const map: Record<number, string> = {};
    for (const employee of employeeData.items) map[employee.id] = employee.name;
    employeeNames.value = map;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载任务失败";
  } finally {
    loading.value = false;
  }
}

async function link(task: TaskRow): Promise<void> {
  linkingId.value = task.id;
  try {
    await api.post(`/projects/${props.projectId}/tasks`, { instance_id: task.id });
    toast.push(`已关联任务：${task.title}`);
    props.onLinked?.();
    modal.close();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "关联失败", "error");
  } finally {
    linkingId.value = null;
  }
}

onMounted(load);
</script>

<template>
  <div class="modal task-link">
    <div class="modal-head">
      <div>
        <h3>关联任务{{ projectName ? ` · ${projectName}` : "" }}</h3>
        <p>选择尚未归属任何项目的任务；关联后 Token 会汇总到项目成本。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <div class="picker-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索任务标题、类型或员工" />
        <span class="muted">{{ filtered.length }} 个</span>
      </div>

      <div v-if="loading" class="muted hint">加载任务…</div>
      <div v-else-if="error" class="hint error">
        <span>{{ error }}</span>
        <button class="btn btn-sm" type="button" @click="load">重试</button>
      </div>
      <div v-else-if="!filtered.length" class="hint muted">
        没有可关联的任务。员工发起任务后，未归属项目的历史任务会出现在这里。
      </div>

      <div v-else class="task-list">
        <button
          v-for="task in filtered"
          :key="task.id"
          type="button"
          class="task-row"
          :disabled="linkingId !== null"
          @click="link(task)"
        >
          <span class="task-main">
            <b>{{ task.title }}</b>
            <small class="mono">
              #{{ task.id }} · {{ task.task_type }}
              <template v-if="task.employee_id">
                · {{ employeeNames[task.employee_id] || `员工 ${task.employee_id}` }}
              </template>
            </small>
          </span>
          <StatusPill :status="task.status" />
          <span class="muted date">{{ fmtDate(task.created_at) }}</span>
          <span class="link-action">{{ linkingId === task.id ? "关联中…" : "关联" }}</span>
        </button>
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">关闭</button>
    </div>
  </div>
</template>

<style scoped>
.task-link {
  width: min(760px, 94vw);
}
.picker-search {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 10px;
  height: 36px;
  background: var(--panel-2);
  margin-bottom: 12px;
}
.picker-search :deep(svg) {
  width: 15px;
  height: 15px;
  color: var(--dim);
}
.picker-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 12.5px;
}
.hint {
  padding: 22px 4px;
  font-size: 12px;
  line-height: 1.7;
}
.hint.error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--coral);
}
.task-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
}
.task-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.task-row:hover:not(:disabled) {
  border-color: var(--amber);
}
.task-row:disabled {
  opacity: 0.7;
  cursor: default;
}
.task-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.task-main b {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-main small {
  font-size: 10px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.date {
  font-size: 10.5px;
  white-space: nowrap;
}
.link-action {
  font-size: 11px;
  color: var(--amber);
  white-space: nowrap;
}
</style>
