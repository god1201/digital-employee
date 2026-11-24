<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import ApprovalDetailDrawer from "@/components/ApprovalDetailDrawer.vue";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ onChanged?: () => void }>();
const drawer = useDrawerStore();
const toast = useToastStore();
const items = ref<any[]>([]);
const total = ref(0);

async function load(): Promise<void> {
  try {
    const data = await api.get<any>("/approvals/notifications?page_size=50");
    items.value = data.items || [];
    total.value = data.total || 0;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function readOne(id: number): Promise<void> {
  try {
    await api.post(`/approvals/notifications/${id}/read`, {});
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

async function readAll(): Promise<void> {
  try {
    const result = await api.post<any>("/approvals/notifications/read-all", {});
    toast.push(`已标记 ${result.updated || 0} 条通知`);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function openInstance(id: number): void {
  drawer.open(ApprovalDetailDrawer, { id, onChanged: props.onChanged });
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>审批通知</h3>
      <p>{{ items.filter((item) => item.status === "unread").length }} 条未读 · 共 {{ total }} 条</p>
    </div>
    <button class="icon-btn" @click="drawer.close()"><AppIcon name="close" /></button>
  </div>

  <div style="display: flex; gap: 8px; margin-bottom: 14px">
    <button class="btn btn-sm btn-ghost" @click="readAll"><AppIcon name="check" />全部已读</button>
    <button class="btn btn-sm btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
  </div>

  <div v-if="!items.length" class="empty">还没有审批通知</div>
  <div
    v-for="item in items"
    :key="item.id"
    class="notification-item"
    :class="{ unread: item.status === 'unread' }"
  >
    <div class="notice-head">
      <b>{{ item.title }}</b>
      <span class="dim mono" style="font-size: 10px">{{ fmtDate(item.created_at) }}</span>
    </div>
    <p>{{ item.content || "" }}</p>
    <div class="asset-actions">
      <button v-if="item.instance_id" class="btn btn-sm" @click="openInstance(item.instance_id)">
        查看审批
      </button>
      <button
        v-if="item.status === 'unread'"
        class="btn btn-sm btn-ghost"
        @click="readOne(item.id)"
      >
        标为已读
      </button>
    </div>
  </div>
</template>
