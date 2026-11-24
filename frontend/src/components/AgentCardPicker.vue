<script setup lang="ts">
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";

const props = withDefaults(
  defineProps<{ agents: any[]; modelValue?: number | null; compact?: boolean }>(),
  { modelValue: null, compact: false },
);
const emit = defineEmits<{
  (event: "update:modelValue", value: number | null): void;
  (event: "select", value: any): void;
}>();

const keyword = ref("");

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return props.agents;
  return props.agents.filter((agent) =>
    [agent.name, agent.code, agent.model_name, ...(agent.capabilities || [])]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

function pick(agent: any): void {
  emit("update:modelValue", agent.id);
  emit("select", agent);
}
</script>

<template>
  <div class="agent-picker">
    <div class="picker-search">
      <AppIcon name="search" />
      <input v-model="keyword" placeholder="搜索 Agent 名称、编码、能力" />
      <span class="muted">{{ filtered.length }} 个</span>
    </div>
    <div class="agent-grid" :class="{ compact }">
      <button
        v-for="agent in filtered"
        :key="agent.id"
        type="button"
        class="agent-card"
        :class="{ selected: modelValue === agent.id }"
        @click="pick(agent)"
      >
        <div class="agent-top">
          <span class="agent-mark">{{ (agent.name || "A").slice(0, 1) }}</span>
          <div class="agent-title">
            <b>{{ agent.name }}</b>
            <small class="mono">{{ agent.code }}</small>
          </div>
          <span v-if="modelValue === agent.id" class="picked">已选</span>
        </div>
        <div class="agent-meta">
          <span class="tag">{{ agent.model_name || "默认模型" }}</span>
          <span class="tag">{{ (agent.tools || []).length }} 个工具</span>
          <span class="tag">{{ (agent.capabilities || []).length }} 项能力</span>
        </div>
        <p v-if="!compact && agent.capabilities?.length" class="caps">
          {{ (agent.capabilities || []).slice(0, 6).join(" · ") }}
        </p>
        <p v-if="!compact && agent.description" class="muted desc">
          {{ agent.description }}
        </p>
      </button>
      <div v-if="!filtered.length" class="empty-pick muted">
        没有匹配的 Agent，先去「Agent」页面注册一个。
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
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
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 2px;
}
.agent-grid.compact {
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  max-height: 280px;
}
.agent-card {
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-2);
  padding: 12px;
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s, background 0.15s;
}
.agent-card:hover {
  border-color: var(--line-strong);
  transform: translateY(-1px);
}
.agent-card.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 10%, var(--panel-2));
}
.agent-top {
  display: flex;
  align-items: center;
  gap: 9px;
}
.agent-mark {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
  font-family: var(--mono);
}
.agent-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.agent-title b {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.agent-title small {
  color: var(--dim);
  font-size: 10.5px;
}
.picked {
  font-size: 10px;
  color: var(--amber);
  border: 1px solid color-mix(in srgb, var(--amber) 40%, transparent);
  border-radius: 999px;
  padding: 2px 7px;
}
.agent-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}
.tag {
  font-size: 10px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
}
.caps {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--dim);
}
.desc {
  margin: 6px 0 0;
  font-size: 10.5px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.empty-pick {
  grid-column: 1 / -1;
  padding: 24px;
  text-align: center;
  font-size: 12px;
}
</style>
