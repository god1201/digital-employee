<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import { useDrawerStore } from "@/stores/drawer";
import { fmtMs } from "@/utils/format";

interface AgentInvokeResult {
  agent_id: number;
  agent_code: string;
  output: unknown;
  tokens: number;
  latency_ms: number;
  tool_calls: unknown[];
}

defineProps<{
  result: AgentInvokeResult;
  agentName?: string;
}>();

const drawer = useDrawerStore();
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>Agent 调用结果</h3>
      <p>
        {{ agentName || result.agent_code }} · {{ result.agent_code }} · {{ result.tokens }} tokens ·
        {{ fmtMs(result.latency_ms) }}
      </p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="section-label">OUTPUT</div>
  <JsonBlock :value="result.output" />

  <div class="section-label">TOOL CALLS</div>
  <JsonBlock :value="result.tool_calls || []" />
</template>
