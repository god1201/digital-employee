<script setup lang="ts">
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";

const props = withDefaults(
  defineProps<{
    projects: any[];
    excludeIds?: number[];
    onSelect?: (project: any) => void;
  }>(),
  { excludeIds: () => [] },
);

const modal = useModalStore();
const keyword = ref("");
const selectedId = ref<number | null>(null);

const statusLabels: Record<string, string> = {
  active: "进行中",
  paused: "已暂停",
  archived: "已归档",
};

const candidates = computed(() =>
  props.projects.filter(
    (project) =>
      !props.excludeIds.includes(project.id) && project.status !== "archived",
  ),
);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return candidates.value;
  return candidates.value.filter((project) =>
    [project.name, project.code, project.description]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

const selected = computed(
  () => candidates.value.find((project) => project.id === selectedId.value) || null,
);

function submit(): void {
  if (!selected.value) return;
  props.onSelect?.(selected.value);
  modal.close();
}
</script>

<template>
  <div class="modal project-picker">
    <div class="modal-head">
      <div>
        <h3>加入项目</h3>
        <p>选择一个项目成为成员；之后可把该员工的任务与会话归集进去。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <div class="picker-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索项目名称、编码或描述" />
        <span class="muted">{{ filtered.length }} 个</span>
      </div>

      <div v-if="filtered.length" class="project-grid">
        <button
          v-for="project in filtered"
          :key="project.id"
          type="button"
          class="project-card"
          :class="{ selected: selectedId === project.id }"
          @click="selectedId = project.id"
        >
          <div class="card-head">
            <b>{{ project.name }}</b>
            <span class="tag">{{ statusLabels[project.status] || project.status }}</span>
          </div>
          <small class="mono">{{ project.code }}</small>
          <div class="card-meta muted">
            <span>{{ project.member_count ?? 0 }} 成员</span>
            <span>{{ project.task_count ?? 0 }} 任务</span>
            <span>{{ project.owner_name || "无负责人" }}</span>
          </div>
        </button>
      </div>
      <div v-else class="empty-pick muted">
        没有可加入的项目。可先新建项目，再回来加入。
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button type="button" class="btn btn-primary" :disabled="!selected" @click="submit">
        加入项目
      </button>
    </div>
  </div>
</template>

<style scoped>
.project-picker {
  width: min(780px, 94vw);
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
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 9px;
  max-height: 380px;
  overflow-y: auto;
}
.project-card {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}
.project-card.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 9%, var(--panel-2));
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-head b {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tag {
  font-size: 10px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
  white-space: nowrap;
}
.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10px;
}
.empty-pick {
  padding: 24px;
  text-align: center;
  font-size: 12px;
}
</style>
