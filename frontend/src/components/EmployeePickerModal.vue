<script setup lang="ts">
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";

const props = withDefaults(
  defineProps<{
    employees: any[];
    excludeIds?: number[];
    title?: string;
    sub?: string;
    submitLabel?: string;
    onSelect?: (employee: any) => void;
  }>(),
  {
    excludeIds: () => [],
    title: "选择数字员工",
    sub: "选择一名数字员工完成操作。",
    submitLabel: "确认",
  },
);

const modal = useModalStore();
const keyword = ref("");
const selectedId = ref<number | null>(null);

const candidates = computed(() =>
  props.employees.filter((employee) => !props.excludeIds.includes(employee.id)),
);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return candidates.value;
  return candidates.value.filter((employee) =>
    [employee.name, employee.code, employee.position, employee.agent_name]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

const selected = computed(
  () => candidates.value.find((employee) => employee.id === selectedId.value) || null,
);

function submit(): void {
  if (!selected.value) return;
  props.onSelect?.(selected.value);
  modal.close();
}
</script>

<template>
  <div class="modal employee-picker">
    <div class="modal-head">
      <div>
        <h3>{{ title }}</h3>
        <p>{{ sub }}</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <div class="picker-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索员工、岗位或 Agent" />
        <span class="muted">{{ filtered.length }} 个</span>
      </div>
      <div class="employee-grid">
        <button
          v-for="employee in filtered"
          :key="employee.id"
          type="button"
          class="employee-card"
          :class="{ selected: selectedId === employee.id }"
          @click="selectedId = employee.id"
        >
          <span class="avatar">{{ (employee.name || "E").slice(0, 1) }}</span>
          <span class="meta">
            <b>{{ employee.name }}</b>
            <small>{{ employee.position || "未设置岗位" }}</small>
            <small class="mono">{{ employee.agent_name || "未绑定 Agent" }}</small>
          </span>
          <span class="check">{{ selectedId === employee.id ? "✓" : "" }}</span>
        </button>
        <div v-if="!filtered.length" class="empty-pick muted">
          没有可选的数字员工。
        </div>
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button type="button" class="btn btn-primary" :disabled="!selected" @click="submit">
        {{ submitLabel }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.employee-picker {
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
.employee-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 8px;
  max-height: 340px;
  overflow-y: auto;
}
.employee-card {
  display: flex;
  align-items: center;
  gap: 9px;
  text-align: left;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}
.employee-card.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 9%, var(--panel-2));
}
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
  font-size: 12px;
  flex-shrink: 0;
}
.meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.meta b {
  font-size: 12.5px;
}
.meta small {
  font-size: 10px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.check {
  width: 18px;
  height: 18px;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
  display: grid;
  place-items: center;
  font-size: 10px;
  color: #10151b;
  flex-shrink: 0;
}
.employee-card.selected .check {
  background: var(--amber);
  border-color: var(--amber);
  font-weight: 700;
}
.empty-pick {
  grid-column: 1 / -1;
  padding: 24px;
  text-align: center;
  font-size: 12px;
}
</style>
