<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import { useModalStore } from "@/stores/modal";

interface ToolItem {
  id: number;
  name: string;
  code: string;
  tool_type?: string;
  risk_level?: string;
  enabled?: boolean;
}

const props = defineProps<{
  tools?: ToolItem[];
  onCreated?: (agent: any) => void;
}>();

const modal = useModalStore();

const steps = ["身份", "模型", "工具", "提示词", "预览"];
const step = ref(0);
const error = ref("");
const submitting = ref(false);
const showAdvanced = ref(false);

const name = ref("");
const code = ref("");
const description = ref("");
const agentType = ref<"internal" | "third_party">("internal");
const protocol = ref<"builtin" | "http" | "openai">("builtin");
const endpointUrl = ref("");
const headersText = ref("{}");
const modelProvider = ref("openai");
const modelName = ref("");
const toolCodes = ref<string[]>([]);
const toolKeyword = ref("");
const capabilitiesText = ref("");
const systemPrompt = ref("");
const configText = ref(JSON.stringify({ max_steps: 6, timeout: 30 }, null, 2));

const toolRows = computed(() => {
  const text = toolKeyword.value.trim().toLowerCase();
  const list = props.tools || [];
  if (!text) return list;
  return list.filter((tool) =>
    [tool.name, tool.code, tool.tool_type, tool.risk_level]
      .join(" ")
      .toLowerCase()
      .includes(text),
  );
});

const selectedTools = computed(() =>
  (props.tools || []).filter((tool) => toolCodes.value.includes(tool.code)),
);

const capabilities = computed(() =>
  capabilitiesText.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
);

const parsedHeaders = computed<Record<string, string>>(() => {
  if (agentType.value === "internal") return {};
  try {
    const value = JSON.parse(headersText.value || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
});

const configPreview = computed<Record<string, unknown>>(() => {
  try {
    const value = JSON.parse(configText.value || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
});

const payload = computed(() => ({
  name: name.value.trim(),
  code: code.value.trim(),
  agent_type: agentType.value,
  protocol: protocol.value,
  description: description.value.trim(),
  endpoint_url: agentType.value === "third_party" ? endpointUrl.value.trim() || null : null,
  headers: parsedHeaders.value,
  model_provider: modelProvider.value.trim() || "openai",
  model_name: modelName.value.trim(),
  system_prompt: systemPrompt.value,
  tools: toolCodes.value,
  capabilities: capabilities.value,
  config: configPreview.value,
  status: "active",
}));

watch(agentType, (value) => {
  protocol.value = value === "internal" ? "builtin" : "http";
  error.value = "";
});

function validateStep(index: number): string {
  if (index === 0) {
    if (!name.value.trim()) return "请填写 Agent 名称";
    if (!code.value.trim()) return "请填写 Agent 编码";
    if (!/^[a-zA-Z0-9_-]+$/.test(code.value.trim())) {
      return "编码只能包含字母、数字、下划线和短横线";
    }
  }
  if (index === 1 && agentType.value === "third_party") {
    if (!/^https?:\/\//.test(endpointUrl.value.trim())) {
      return "第三方 Agent 需要填写以 http(s):// 开头的 Endpoint URL";
    }
    try {
      JSON.parse(headersText.value || "{}");
    } catch {
      return "请求头必须是合法的 JSON 对象";
    }
  }
  if (index === 4) {
    try {
      JSON.parse(configText.value || "{}");
    } catch {
      return "高级配置必须是合法的 JSON 对象";
    }
  }
  return "";
}

function next(): void {
  const message = validateStep(step.value);
  if (message) {
    error.value = message;
    return;
  }
  error.value = "";
  step.value = Math.min(step.value + 1, steps.length - 1);
}

function back(): void {
  error.value = "";
  step.value = Math.max(step.value - 1, 0);
}

function toggleTool(tool: ToolItem): void {
  const index = toolCodes.value.indexOf(tool.code);
  if (index >= 0) toolCodes.value.splice(index, 1);
  else toolCodes.value.push(tool.code);
}

async function submit(): Promise<void> {
  const message = validateStep(4) || validateStep(1) || validateStep(0);
  if (message) {
    error.value = message;
    const target = message.includes("Endpoint") || message.includes("请求头") ? 1 : 0;
    step.value = target;
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    const agent = await api.post<any>("/agents", payload.value);
    props.onCreated?.(agent);
    modal.close();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "注册 Agent 失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal agent-wizard">
    <div class="modal-head">
      <div>
        <h3>新建 Agent</h3>
        <p>Agent 是可复用能力单元：先配置身份、模型和工具，再绑定给数字员工。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>

    <div class="wizard-steps">
      <button
        v-for="(label, index) in steps"
        :key="label"
        type="button"
        class="wizard-step"
        :class="{ active: step === index, done: index < step }"
        @click="index <= step ? (step = index) : null"
      >
        <span class="dot">{{ index < step ? "✓" : index + 1 }}</span>
        <span>{{ label }}</span>
      </button>
    </div>

    <div class="modal-body wizard-body">
      <section v-if="step === 0" class="wizard-panel">
        <div class="form-grid two">
          <label class="field">
            <span>名称 <i>*</i></span>
            <input v-model="name" placeholder="例如：应收复核 Agent" />
          </label>
          <label class="field">
            <span>编码 <i>*</i></span>
            <input v-model="code" placeholder="ar_reviewer" class="mono" />
          </label>
        </div>
        <label class="field">
          <span>描述</span>
          <input v-model="description" placeholder="这个 Agent 擅长什么、被谁复用" />
        </label>
        <div class="field">
          <span>类型</span>
          <div class="choice-row">
            <button
              type="button"
              class="choice"
              :class="{ selected: agentType === 'internal' }"
              @click="agentType = 'internal'"
            >
              <b>内置 Agent</b>
              <small>平台内 ReAct 循环，绑定工具后直接可用</small>
            </button>
            <button
              type="button"
              class="choice"
              :class="{ selected: agentType === 'third_party' }"
              @click="agentType = 'third_party'"
            >
              <b>第三方 Agent</b>
              <small>外部 endpoint，通过 openai / http 协议接入</small>
            </button>
          </div>
        </div>
      </section>

      <section v-else-if="step === 1" class="wizard-panel">
        <div class="form-grid two">
          <label class="field">
            <span>模型提供方</span>
            <input v-model="modelProvider" placeholder="openai / deepseek / local" />
          </label>
          <label class="field">
            <span>模型名称</span>
            <input v-model="modelName" placeholder="deepseek-chat" />
          </label>
        </div>
        <template v-if="agentType === 'third_party'">
          <div class="form-grid two">
            <label class="field">
              <span>协议</span>
              <select v-model="protocol">
                <option value="http">http</option>
                <option value="openai">openai</option>
              </select>
            </label>
            <label class="field">
              <span>Endpoint URL <i>*</i></span>
              <input v-model="endpointUrl" placeholder="https://agent.example.com/invoke" />
            </label>
          </div>
          <label class="field">
            <span>请求头 JSON（可选，用于鉴权）</span>
            <textarea v-model="headersText" rows="4" class="mono" spellcheck="false" />
          </label>
        </template>
        <div v-else class="hint-card">
          内置 Agent 固定使用 <b class="mono">builtin</b> 协议，由平台执行工具调用与步数预算。
        </div>
      </section>

      <section v-else-if="step === 2" class="wizard-panel">
        <div class="tool-bar">
          <div class="picker-search">
            <AppIcon name="search" />
            <input v-model="toolKeyword" placeholder="搜索工具名称、编码、风险等级" />
          </div>
          <span class="muted">已选 {{ toolCodes.length }} 个</span>
        </div>
        <div v-if="toolRows.length" class="tool-grid">
          <button
            v-for="tool in toolRows"
            :key="tool.id"
            type="button"
            class="tool-card"
            :class="{ selected: toolCodes.includes(tool.code) }"
            @click="toggleTool(tool)"
          >
            <span class="tool-check">{{ toolCodes.includes(tool.code) ? "✓" : "" }}</span>
            <span class="tool-main">
              <b>{{ tool.name }}</b>
              <small class="mono">{{ tool.code }}</small>
            </span>
            <span class="tag" :class="`risk-${tool.risk_level || 'low'}`">
              {{ tool.risk_level || "low" }}
            </span>
          </button>
        </div>
        <div v-else class="hint-card">
          没有可绑定的工具。可先到「能力接入 → 工具」创建工具，或跳过这一步稍后再绑定。
        </div>
      </section>

      <section v-else-if="step === 3" class="wizard-panel">
        <label class="field">
          <span>系统提示词</span>
          <textarea
            v-model="systemPrompt"
            rows="8"
            placeholder="描述 Agent 的角色、流程与输出要求。数字员工可在此基础上追加员工级提示词。"
          />
        </label>
        <label class="field">
          <span>能力标签（逗号分隔）</span>
          <input v-model="capabilitiesText" placeholder="对账, 回款, 报表" />
        </label>
        <div class="hint-card">
          能力标签用于员工绑定、群聊路由和技能市场匹配，建议 2–6 个。
        </div>
      </section>

      <section v-else class="wizard-panel">
        <div class="review-grid">
          <div class="review-item">
            <span>名称 / 编码</span>
            <b>{{ payload.name || "—" }}</b>
            <small class="mono">{{ payload.code || "—" }}</small>
          </div>
          <div class="review-item">
            <span>类型 / 协议</span>
            <b>{{ agentType === "internal" ? "内置" : "第三方" }}</b>
            <small class="mono">{{ protocol }}</small>
          </div>
          <div class="review-item">
            <span>模型</span>
            <b class="mono">{{ modelName || "默认模型" }}</b>
            <small>{{ modelProvider }}</small>
          </div>
          <div class="review-item">
            <span>工具</span>
            <b>{{ toolCodes.length }} 个</b>
            <small class="mono">{{ selectedTools.map((tool) => tool.code).join(", ") || "未绑定" }}</small>
          </div>
        </div>

        <div class="review-block">
          <span class="section-label">能力标签</span>
          <div class="chip-row">
            <span v-for="cap in capabilities" :key="cap" class="tag">{{ cap }}</span>
            <span v-if="!capabilities.length" class="muted" style="font-size: 11px">未填写</span>
          </div>
        </div>

        <div class="review-block">
          <span class="section-label">系统提示词</span>
          <p class="prompt-preview">{{ systemPrompt || "未填写，将使用平台默认提示词。" }}</p>
        </div>

        <button type="button" class="advanced-toggle" @click="showAdvanced = !showAdvanced">
          <AppIcon name="layers" />
          高级配置（JSON）
          <span class="muted">{{ showAdvanced ? "收起" : "展开" }}</span>
        </button>
        <div v-if="showAdvanced" class="advanced-block">
          <textarea
            v-model="configText"
            rows="6"
            class="mono"
            spellcheck="false"
            placeholder='{"max_steps": 6, "timeout": 30}'
          />
        </div>

        <span class="section-label">提交预览</span>
        <JsonBlock :value="payload" />
      </section>

      <div class="form-error" :class="{ show: error }">{{ error }}</div>
    </div>

    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
      <button v-if="step > 0" type="button" class="btn btn-ghost" @click="back">上一步</button>
      <button v-if="step < steps.length - 1" type="button" class="btn btn-primary" @click="next">
        下一步
      </button>
      <button
        v-else
        type="button"
        class="btn btn-primary"
        :disabled="submitting"
        @click="submit"
      >
        {{ submitting ? "注册中…" : "注册 Agent" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.agent-wizard {
  width: min(820px, 94vw);
}
.wizard-steps {
  display: flex;
  gap: 6px;
  padding: 0 22px 14px;
  flex-wrap: wrap;
}
.wizard-step {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--dim);
  font-size: 11px;
  padding: 4px 10px 4px 5px;
  cursor: pointer;
}
.wizard-step .dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 10px;
  background: rgba(255, 255, 255, 0.05);
}
.wizard-step.active {
  color: var(--text);
  border-color: var(--amber);
}
.wizard-step.active .dot {
  background: var(--amber);
  color: #10151b;
  font-weight: 700;
}
.wizard-step.done {
  color: var(--text);
  border-color: color-mix(in srgb, var(--amber) 45%, var(--line));
}
.wizard-step.done .dot {
  color: var(--amber);
  background: rgba(232, 163, 61, 0.14);
}
.wizard-body {
  min-height: 320px;
}
.wizard-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.field input,
.field select,
.field textarea {
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
  padding: 8px 10px;
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
}
.field input,
.field select {
  height: 34px;
}
.field textarea {
  resize: vertical;
  line-height: 1.6;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: var(--amber);
}
.choice-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.choice {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}
.choice small {
  color: var(--dim);
  font-size: 10.5px;
  line-height: 1.5;
}
.choice.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 10%, var(--panel-2));
}
.hint-card {
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 11.5px;
  color: var(--dim);
  line-height: 1.7;
}
.tool-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.picker-search {
  flex: 1;
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
.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
  padding-right: 2px;
}
.tool-card {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.tool-card.selected {
  border-color: var(--amber);
  background: color-mix(in srgb, var(--amber) 9%, var(--panel-2));
}
.tool-check {
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
.tool-card.selected .tool-check {
  background: var(--amber);
  border-color: var(--amber);
  font-weight: 700;
}
.tool-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.tool-main b {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tool-main small {
  color: var(--dim);
  font-size: 10px;
}
.tag {
  font-size: 10px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
  white-space: nowrap;
}
.risk-high,
.risk-critical {
  color: var(--coral);
  border-color: color-mix(in srgb, var(--coral) 40%, transparent);
}
.risk-medium {
  color: var(--amber);
  border-color: color-mix(in srgb, var(--amber) 40%, transparent);
}
.review-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.review-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.review-item span {
  font-size: 10px;
  color: var(--dim);
}
.review-item b {
  font-size: 12.5px;
}
.review-item small {
  font-size: 10px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.review-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.section-label {
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--dim);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.prompt-preview {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 10px 12px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: transparent;
  color: var(--text);
  font-size: 11.5px;
  padding: 8px 11px;
  cursor: pointer;
}
.advanced-toggle :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--dim);
}
.advanced-toggle .muted {
  margin-left: auto;
}
.advanced-block textarea {
  width: 100%;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
  padding: 10px;
  font-size: 11px;
  line-height: 1.6;
  resize: vertical;
}
@media (max-width: 720px) {
  .form-grid.two,
  .choice-row,
  .review-grid {
    grid-template-columns: 1fr;
  }
}
</style>
