<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import ChatDrawer from "@/components/ChatDrawer.vue";
import GroupChatModal from "@/components/GroupChatModal.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const items = ref<any[]>([]);
const loading = ref(false);
const keyword = ref("");

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return items.value;
  return items.value.filter((item) =>
    [item.title, ...(item.member_names || []), item.last_message]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    items.value = await api.get<any[]>("/conversations?limit=100");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载会话失败", "error");
  } finally {
    loading.value = false;
  }
}

function openChat(item: any): void {
  drawer.open(ChatDrawer, { conversationId: item.id, employee: null });
}

async function createGroup(): Promise<void> {
  try {
    const employees = await api.get<any>("/digital-employees?page_size=200");
    modal.openCustom(GroupChatModal, {
      employees: employees.items,
      onCreate: async (payload: { title: string; employee_ids: number[] }) => {
        try {
          const result = await api.post<any>("/conversations", {
            mode: "group",
            title: payload.title,
            employee_ids: payload.employee_ids,
          });
          toast.push("群聊已创建");
          await load();
          drawer.open(ChatDrawer, {
            conversationId: result.conversation.id,
            employee: null,
          });
        } catch (err) {
          toast.push(err instanceof Error ? err.message : "创建群聊失败", "error");
        }
      },
    });
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载员工失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="workforce / conversations"
    title="会话"
    sub="与单个数字员工对话，或把多个员工拉进群聊协作。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load">
        <AppIcon name="refresh" />刷新
      </button>
      <button class="btn btn-primary" @click="createGroup">
        <AppIcon name="users" />新建群聊
      </button>
    </template>
  </PageHeader>

  <div class="conversation-toolbar">
    <div class="roster-search">
      <AppIcon name="search" />
      <input v-model="keyword" placeholder="搜索会话、员工或消息摘要" />
    </div>
    <span class="muted">{{ filtered.length }} 个会话</span>
  </div>

  <div v-if="loading" class="panel muted conversations-loading">加载会话…</div>
  <div v-else-if="!filtered.length" class="panel conversations-empty">
    <AppIcon name="spark" />
    <b>还没有会话</b>
    <p class="muted">从数字员工工作台点击「去对话」，或创建一个群聊。</p>
    <button class="btn btn-primary" @click="createGroup">新建群聊</button>
  </div>
  <div v-else class="conversation-grid">
    <button
      v-for="item in filtered"
      :key="item.id"
      type="button"
      class="conversation-card"
      @click="openChat(item)"
    >
      <div class="conversation-head">
        <span class="conversation-mark">
          {{ item.mode === "group" ? "群" : (item.member_names?.[0] || "E").slice(0, 1) }}
        </span>
        <div>
          <b>{{ item.title }}</b>
          <small>{{ item.mode === "group" ? "群聊" : "直接对话" }} · {{ (item.member_names || []).join("、") }}</small>
        </div>
        <span class="tag">{{ item.last_message_at ? fmtDate(item.last_message_at) : "新会话" }}</span>
      </div>
      <p class="conversation-preview">
        {{ item.last_message || "还没有消息，打开会话开始工作。" }}
      </p>
      <span class="conversation-open">打开对话 <AppIcon name="arrow" /></span>
    </button>
  </div>
</template>

<style scoped>
.conversation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.roster-search {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 0 10px;
  height: 34px;
  width: min(420px, 70vw);
}
.roster-search :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--dim);
}
.roster-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 12px;
}
.conversations-loading {
  padding: 24px;
  font-size: 12px;
}
.conversations-empty {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  color: var(--dim);
}
.conversations-empty :deep(svg) {
  width: 34px;
  height: 34px;
  color: var(--amber);
}
.conversations-empty b {
  color: var(--text);
}
.conversation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 10px;
}
.conversation-card {
  border: 1px solid var(--line);
  border-radius: 13px;
  background: var(--panel);
  color: var(--text);
  text-align: left;
  padding: 13px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}
.conversation-card:hover {
  border-color: var(--line-strong);
  transform: translateY(-1px);
}
.conversation-head {
  display: flex;
  align-items: center;
  gap: 9px;
}
.conversation-mark {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-weight: 700;
  flex: 0 0 auto;
}
.conversation-head > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.conversation-head b {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conversation-head small {
  font-size: 9.5px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tag {
  font-size: 9px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 6px;
  white-space: nowrap;
}
.conversation-preview {
  margin: 0;
  font-size: 11px;
  color: var(--dim);
  line-height: 1.6;
  min-height: 35px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.conversation-open {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--amber);
}
.conversation-open :deep(svg) {
  width: 12px;
  height: 12px;
}
</style>
