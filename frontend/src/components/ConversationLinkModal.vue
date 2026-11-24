<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface ConversationRow {
  id: number;
  title: string;
  mode: string;
  status: string;
  project_id?: number | null;
  last_message_at?: string | null;
}

const props = defineProps<{
  projectId: number;
  projectName?: string;
  onLinked?: () => void;
}>();

const modal = useModalStore();
const toast = useToastStore();

const rows = ref<ConversationRow[]>([]);
const loading = ref(true);
const error = ref("");
const keyword = ref("");
const linkingId = ref<number | null>(null);

const candidates = computed(() =>
  rows.value.filter((item) => !item.project_id && item.status === "active"),
);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return candidates.value;
  return candidates.value.filter((item) =>
    [item.title, item.mode].join(" ").toLowerCase().includes(text),
  );
});

const modeLabel: Record<string, string> = {
  direct: "直接对话",
  group: "群聊",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    rows.value = await api.get<ConversationRow[]>("/conversations?limit=200");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载会话失败";
  } finally {
    loading.value = false;
  }
}

async function link(item: ConversationRow): Promise<void> {
  linkingId.value = item.id;
  try {
    await api.post(`/projects/${props.projectId}/conversations`, {
      conversation_id: item.id,
    });
    toast.push(`已关联会话：${item.title || `#${item.id}`}`);
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
  <div class="modal conversation-link">
    <div class="modal-head">
      <div>
        <h3>关联会话{{ projectName ? ` · ${projectName}` : "" }}</h3>
        <p>把尚未归属项目的直接对话或群聊归集到项目，Token 会一并汇总。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <div class="picker-search">
        <AppIcon name="search" />
        <input v-model="keyword" placeholder="搜索会话标题或类型" />
        <span class="muted">{{ filtered.length }} 个</span>
      </div>

      <div v-if="loading" class="muted hint">加载会话…</div>
      <div v-else-if="error" class="hint error">
        <span>{{ error }}</span>
        <button class="btn btn-sm" type="button" @click="load">重试</button>
      </div>
      <div v-else-if="!filtered.length" class="hint muted">
        没有可关联的会话。新建直接对话或群聊后，未归属项目的会话会出现在这里。
      </div>

      <div v-else class="conversation-list">
        <button
          v-for="item in filtered"
          :key="item.id"
          type="button"
          class="conversation-row"
          :disabled="linkingId !== null"
          @click="link(item)"
        >
          <span class="conversation-main">
            <b>{{ item.title || `会话 #${item.id}` }}</b>
            <small class="mono">
              #{{ item.id }} · {{ modeLabel[item.mode] || item.mode }}
            </small>
          </span>
          <span class="muted date">
            {{ item.last_message_at ? fmtDate(item.last_message_at) : "暂无消息" }}
          </span>
          <span class="link-action">{{ linkingId === item.id ? "关联中…" : "关联" }}</span>
        </button>
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">关闭</button>
    </div>
  </div>
</template>

<style scoped>
.conversation-link {
  width: min(720px, 94vw);
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
.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
}
.conversation-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
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
.conversation-row:hover:not(:disabled) {
  border-color: var(--amber);
}
.conversation-row:disabled {
  opacity: 0.7;
  cursor: default;
}
.conversation-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.conversation-main b {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conversation-main small {
  font-size: 10px;
  color: var(--dim);
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
