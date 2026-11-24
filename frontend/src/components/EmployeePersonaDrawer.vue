<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { ApiError, api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";

interface Employee {
  id: number;
  name: string;
  code: string;
  position?: string | null;
}

const props = defineProps<{ employee: Employee; onChanged?: () => void }>();

const drawer = useDrawerStore();
const toast = useToastStore();
const loading = ref(true);
const saving = ref(false);
const version = ref(0);
const context = ref("");

const form = reactive({
  tone: "professional",
  address_style: "",
  output_format: "conclusion_first",
  report_style: "conclusion_first",
  taboo_words: "",
  signature: "",
  polish_enabled: "false",
  extra_instructions: "",
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await api.get<any>(`/digital-employees/${props.employee.id}/persona`);
    version.value = data.version;
    form.tone = data.tone;
    form.address_style = data.address_style || "";
    form.output_format = data.output_format;
    form.report_style = data.report_style;
    form.taboo_words = (data.taboo_words || []).join("\n");
    form.signature = data.signature || "";
    form.polish_enabled = String(data.polish_enabled);
    form.extra_instructions = data.extra_instructions || "";
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      toast.push(err instanceof Error ? err.message : "加载失败", "error");
    }
  } finally {
    loading.value = false;
  }
  await loadContext();
}

async function loadContext(): Promise<void> {
  try {
    const data = await api.get<any>(
      `/digital-employees/${props.employee.id}/persona/context`,
    );
    context.value = data.context || "";
  } catch {
    context.value = "";
  }
}

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const data = await api.put<any>(`/digital-employees/${props.employee.id}/persona`, {
      tone: form.tone,
      address_style: form.address_style || null,
      output_format: form.output_format,
      report_style: form.report_style,
      taboo_words: lines(form.taboo_words),
      signature: form.signature || null,
      polish_enabled: form.polish_enabled === "true",
      extra_instructions: form.extra_instructions,
    });
    version.value = data.version;
    toast.push("人格风格已保存");
    await loadContext();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "保存失败", "error");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee.name }} · 人格风格</h3>
      <p>{{ employee.code }} · 技能只输出结构，人格层统一表达</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>版本</span><b class="mono">v{{ version || "—" }}</b></div>
      <div class="meta">
        <span>统一润色</span>
        <b><StatusPill :status="form.polish_enabled === 'true' ? 'active' : 'draft'" /></b>
      </div>
    </div>

    <div class="section-label">风格卡</div>
    <div class="form-grid">
      <div class="field">
        <label>语气</label>
        <select v-model="form.tone">
          <option value="professional">专业克制</option>
          <option value="friendly">亲和友好</option>
          <option value="concise">极简直接</option>
          <option value="formal">正式书面</option>
        </select>
      </div>
      <div class="field">
        <label>称呼习惯</label>
        <input v-model="form.address_style" placeholder="例如：称呼王哥" />
      </div>
      <div class="field">
        <label>输出格式</label>
        <select v-model="form.output_format">
          <option value="conclusion_first">结论先行</option>
          <option value="bullets">要点列表</option>
          <option value="table">表格优先（≤5 列）</option>
          <option value="detailed">详细论证</option>
        </select>
      </div>
      <div class="field">
        <label>汇报风格</label>
        <select v-model="form.report_style">
          <option value="conclusion_first">结论 + 依据 + 下一步</option>
          <option value="detailed">完整背景与分析</option>
          <option value="bullets">短要点</option>
        </select>
      </div>
      <div class="field">
        <label>是否启用 LLM 统一润色</label>
        <select v-model="form.polish_enabled">
          <option value="false">关闭（只注入风格约束）</option>
          <option value="true">开启（LLM 步骤输出后润色）</option>
        </select>
      </div>
      <div class="field">
        <label>落款</label>
        <input v-model="form.signature" placeholder="例如：财务部" />
      </div>
      <div class="field full">
        <label>禁忌词（每行一个）</label>
        <textarea v-model="form.taboo_words" rows="3" placeholder="绝对&#10;百分百" />
      </div>
      <div class="field full">
        <label>额外要求</label>
        <textarea v-model="form.extra_instructions" rows="3" />
      </div>
    </div>

    <div class="split" style="margin-top: 16px">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        {{ saving ? "保存中…" : "保存人格风格" }}
      </button>
      <button class="btn btn-ghost" @click="drawer.close()">关闭</button>
    </div>

    <div class="section-label">将注入提示词的人格上下文</div>
    <pre class="code">{{ context || "（未配置）" }}</pre>
  </template>
</template>
