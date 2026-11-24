<script setup lang="ts">
import { computed, ref } from "vue";

import AgentCardPicker from "@/components/AgentCardPicker.vue";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";

const props = defineProps<{
  agents: any[];
  currentId?: number | null;
  onSelect?: (agent: any) => void;
}>();

const modal = useModalStore();
const selectedId = ref<number | null>(props.currentId ?? null);
const selected = computed(
  () => props.agents.find((agent) => agent.id === selectedId.value) || null,
);

function submit(): void {
  if (!selected.value) return;
  props.onSelect?.(selected.value);
  modal.close();
}
</script>

<template>
  <div class="modal agent-picker-modal">
    <div class="modal-head">
      <div>
        <h3>绑定 Agent</h3>
        <p>Agent 是可复用能力单元；更换后员工下一轮对话立即生效。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <div class="modal-body">
      <AgentCardPicker
        :agents="agents"
        :model-value="selectedId"
        @update:model-value="selectedId = $event"
      />
      <div v-if="selected" class="selected-hint">
        已选择 <b>{{ selected.name }}</b> · {{ selected.model_name || "默认模型" }}
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button type="button" class="btn btn-primary" :disabled="!selected" @click="submit">
        绑定
      </button>
    </div>
  </div>
</template>

<style scoped>
.agent-picker-modal {
  width: min(820px, 94vw);
}
.selected-hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--dim);
}
.selected-hint b {
  color: var(--text);
}
</style>
