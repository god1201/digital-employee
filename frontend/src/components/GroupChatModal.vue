<script setup lang="ts">
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";

const props = defineProps<{
  employees: any[];
  onCreate?: (payload: { title: string; employee_ids: number[] }) => void;
}>();

const modal = useModalStore();
const title = ref("");
const keyword = ref("");
const selected = ref<number[]>([]);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return props.employees;
  return props.employees.filter((employee) =>
    [employee.name, employee.position, employee.code, employee.agent_name]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

function toggle(employee: any): void {
  const index = selected.value.indexOf(employee.id);
  if (index >= 0) selected.value.splice(index, 1);
  else selected.value.push(employee.id);
}

function submit(): void {
  if (selected.value.length < 2) return;
  props.onCreate?.({
    title: title.value.trim(),
    employee_ids: [...selected.value],
  });
  modal.close();
}
</script>

<template>
  <div class="modal group-chat-modal">
    <div class="modal-head">
      <div>
        <h3>创建群聊</h3>
        <p>选择多个数字员工；群聊里每个员工保留自己的 Agent、契约与工具。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <label class="field">
        <span>群聊名称（可选）</span>
        <input v-model="title" placeholder="例如：回款专项协作群" />
      </label>
      <div class="picker-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索员工、岗位或 Agent" />
        <span class="muted">已选 {{ selected.length }}</span>
      </div>
      <div class="employee-grid">
        <button
          v-for="employee in filtered"
          :key="employee.id"
          type="button"
          class="employee-card"
          :class="{ selected: selected.includes(employee.id) }"
          @click="toggle(employee)"
        >
          <span class="check">{{ selected.includes(employee.id) ? "✓" : "" }}</span>
          <span class="avatar">{{ (employee.name || "E").slice(0, 1) }}</span>
          <span class="meta">
            <b>{{ employee.name }}</b>
            <small>{{ employee.position || "未设置岗位" }}</small>
            <small class="mono">{{ employee.agent_name || "未绑定 Agent" }}</small>
          </span>
        </button>
        <div v-if="!filtered.length" class="muted empty">没有匹配的员工</div>
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="selected.length < 2"
        @click="submit"
      >
        创建群聊（{{ selected.length }}）
      </button>
    </div>
  </div>
</template>

<style scoped>
.group-chat-modal {
  width: min(760px, 94vw);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
  color: var(--dim);
  margin-bottom: 12px;
}
.field input {
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
  padding: 0 10px;
  font-size: 12.5px;
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
.employee-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 9px;
  max-height: 330px;
  overflow-y: auto;
}
.employee-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  color: var(--text);
  padding: 10px;
  text-align: left;
  cursor: pointer;
}
.employee-card.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 9%, var(--panel-2));
}
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
}
.meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}
.meta b {
  font-size: 12.5px;
}
.meta small {
  font-size: 10.5px;
  color: var(--dim);
}
.check {
  position: absolute;
  top: 6px;
  right: 8px;
  font-size: 11px;
  color: var(--amber);
}
.empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 24px;
}
</style>
