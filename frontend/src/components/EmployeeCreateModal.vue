<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { api } from "@/api/client";
import AgentCardPicker from "@/components/AgentCardPicker.vue";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";

const props = defineProps<{
  agents: any[];
  onCreated?: (employee: any) => void;
}>();

const modal = useModalStore();
const error = ref("");
const submitting = ref(false);
const name = ref("");
const code = ref("");
const position = ref("");
const description = ref("");
const systemPrompt = ref("");
const agentId = ref<number | null>(null);
const modelName = ref("");

const selectedAgent = computed(
  () => props.agents.find((agent) => agent.id === agentId.value) || null,
);

watch(selectedAgent, (agent) => {
  if (!agent) return;
  if (!modelName.value) modelName.value = agent.model_name || "";
});

function pickAgent(agent: any): void {
  agentId.value = agent.id;
  modelName.value = agent.model_name || "";
}

async function submit(): Promise<void> {
  error.value = "";
  if (!name.value.trim() || !code.value.trim()) {
    error.value = "请填写员工姓名与编码";
    return;
  }
  if (!agentId.value) {
    error.value = "请选择一个已有 Agent";
    return;
  }
  submitting.value = true;
  try {
    const employee = await api.post<any>("/digital-employees", {
      name: name.value.trim(),
      code: code.value.trim(),
      position: position.value.trim() || null,
      description: description.value.trim() || null,
      status: "active",
      agent_id: agentId.value,
      model_provider: selectedAgent.value?.model_provider || "openai",
      model_name: modelName.value.trim(),
      system_prompt: systemPrompt.value,
      config: {},
    });
    props.onCreated?.(employee);
    modal.close();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal employee-create">
    <div class="modal-head">
      <div>
        <h3>新增数字员工</h3>
        <p>先选择一个已有 Agent，再配置岗位身份。Agent 可被多个员工复用。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>

    <div class="modal-body">
      <div class="form-section-title">1 · 岗位身份</div>
      <div class="form-grid two">
        <label class="field">
          <span>姓名 <i>*</i></span>
          <input v-model="name" placeholder="例如：应收账款专员 A" />
        </label>
        <label class="field">
          <span>编码 <i>*</i></span>
          <input v-model="code" placeholder="ar_specialist_a" />
        </label>
        <label class="field">
          <span>岗位</span>
          <input v-model="position" placeholder="应收账款 / 客服 / 财务" />
        </label>
        <label class="field">
          <span>职责描述</span>
          <input v-model="description" placeholder="负责回款催收、对账与月报" />
        </label>
      </div>

      <div class="form-section-title">2 · 绑定 Agent</div>
      <AgentCardPicker
        v-if="agents.length"
        :agents="agents"
        :model-value="agentId"
        compact
        @select="pickAgent"
      />
      <div v-else class="empty-agent">
        还没有可复用的 Agent。请先到「能力接入 → Agent」创建一个，再回来创建数字员工。
      </div>

      <div class="form-section-title">3 · 运行配置</div>
      <div class="form-grid two">
        <label class="field">
          <span>模型（默认继承 Agent）</span>
          <input v-model="modelName" placeholder="deepseek-chat" />
        </label>
        <label class="field">
          <span>系统提示词</span>
          <input v-model="systemPrompt" placeholder="员工级补充提示词，可留空" />
        </label>
      </div>

      <div class="form-error" :class="{ show: error }">{{ error }}</div>
    </div>

    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="submitting || !agents.length"
        @click="submit"
      >
        {{ submitting ? "创建中…" : "创建员工" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.employee-create {
  width: min(780px, 94vw);
}
.form-section-title {
  margin: 18px 0 10px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--dim);
}
.form-section-title:first-child {
  margin-top: 0;
}
.form-grid.two {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
  color: var(--dim);
}
.field i {
  color: var(--coral);
  font-style: normal;
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
.empty-agent {
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  padding: 18px;
  font-size: 12px;
  color: var(--dim);
  line-height: 1.7;
}
</style>
