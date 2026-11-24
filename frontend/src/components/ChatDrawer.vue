<script setup lang="ts">
import ChatPanel from "@/components/ChatPanel.vue";
import AppIcon from "@/components/AppIcon.vue";
import { useDrawerStore } from "@/stores/drawer";

const props = defineProps<{
  employee?: { id: number; name: string } | null;
  conversationId?: number | null;
}>();
const drawer = useDrawerStore();
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee?.name ? `与 ${employee.name} 对话` : "数字员工对话" }}</h3>
      <p>可以直接下达工作指令，员工会按岗位契约调用工具。</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>
  <div class="chat-drawer-body">
    <ChatPanel
      :employee-id="props.employee?.id ?? null"
      :conversation-id="props.conversationId ?? null"
      compact
    />
  </div>
</template>

<style scoped>
.chat-drawer-body {
  height: calc(100vh - 86px);
  min-height: 420px;
}
</style>
