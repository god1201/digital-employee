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
const contractId = ref<number | null>(null);
const version = ref(0);
const status = ref("active");

const form = reactive({
  role: "",
  report_to: "",
  report_freq: "",
  work_hours: "",
  autonomy_level: "L2",
  can_do: "",
  cannot_do: "",
  must_ask: "",
  escalation_path: "",
  kpi: "{}",
  autonomy_overrides: "{}",
  red_lines: JSON.stringify(
    {
      read_only: false,
      forbidden_tools: [],
      allowed_tools: [],
      amount_threshold: null,
      amount_field: "amount",
      count_threshold: null,
      count_field: "count",
      sandbox_required: false,
    },
    null,
    2,
  ),
});

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toText(value: unknown): string {
  return Array.isArray(value) ? value.join("\n") : "";
}

function toJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJson(value: string, label: string): Record<string, any> {
  try {
    const parsed = JSON.parse(value || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("必须是 JSON 对象");
    }
    return parsed;
  } catch {
    throw new Error(`「${label}」不是合法的 JSON 对象`);
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await api.get<any>(`/digital-employees/${props.employee.id}/contract`);
    contractId.value = data.id;
    version.value = data.version;
    status.value = data.status;
    form.role = data.role || props.employee.position || "";
    form.report_to = data.report_to || "";
    form.report_freq = data.report_freq || "";
    form.work_hours = data.work_hours || "";
    form.autonomy_level = data.autonomy_level || "L2";
    form.can_do = toText(data.can_do);
    form.cannot_do = toText(data.cannot_do);
    form.must_ask = toText(data.must_ask);
    form.escalation_path = toText(data.escalation_path);
    form.kpi = toJson(data.kpi);
    form.autonomy_overrides = toJson(data.autonomy_overrides);
    form.red_lines = toJson(data.red_lines);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      form.role = props.employee.position || "";
    } else {
      toast.push(err instanceof Error ? err.message : "加载契约失败", "error");
    }
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const payload = {
      role: form.role,
      report_to: form.report_to || null,
      report_freq: form.report_freq || null,
      work_hours: form.work_hours || null,
      autonomy_level: form.autonomy_level,
      can_do: lines(form.can_do),
      cannot_do: lines(form.cannot_do),
      must_ask: lines(form.must_ask),
      escalation_path: lines(form.escalation_path),
      kpi: parseJson(form.kpi, "KPI"),
      autonomy_overrides: parseJson(form.autonomy_overrides, "自主权覆盖"),
      red_lines: parseJson(form.red_lines, "权限红线"),
      status: status.value === "archived" ? "active" : status.value,
    };
    const data = await api.put<any>(
      `/digital-employees/${props.employee.id}/contract`,
      payload,
    );
    contractId.value = data.id;
    version.value = data.version;
    status.value = data.status;
    toast.push("岗位契约已保存");
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
      <h3>{{ employee.name }} · 岗位契约</h3>
      <p>{{ employee.code }} · 契约层仅允许人工修改</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta">
        <span>契约状态</span>
        <b><StatusPill :status="status" /></b>
      </div>
      <div class="meta">
        <span>版本</span>
        <b class="mono">v{{ version || "—" }}</b>
      </div>
      <div class="meta">
        <span>契约 ID</span>
        <b class="mono">{{ contractId ?? "未创建" }}</b>
      </div>
    </div>

    <div class="section-label">身份与汇报</div>
    <div class="form-grid">
      <div class="field">
        <label>岗位角色</label>
        <input v-model="form.role" placeholder="例如：应收账款专员" />
      </div>
      <div class="field">
        <label>自主权等级</label>
        <select v-model="form.autonomy_level">
          <option value="L0">L0 · 只答不做</option>
          <option value="L1">L1 · 建议待批</option>
          <option value="L2">L2 · 低风险自主</option>
          <option value="L3">L3 · 全流程自主</option>
        </select>
      </div>
      <div class="field">
        <label>汇报对象</label>
        <input v-model="form.report_to" placeholder="财务主管-张三" />
      </div>
      <div class="field">
        <label>汇报频率</label>
        <input v-model="form.report_freq" placeholder="每日 18:00 日报 + 异常实时" />
      </div>
      <div class="field full">
        <label>工作时段</label>
        <input v-model="form.work_hours" placeholder="工作日 09:00–18:00" />
      </div>
    </div>

    <div class="section-label">职责边界（每行一条）</div>
    <div class="form-grid">
      <div class="field full">
        <label>可以做 · can_do</label>
        <textarea v-model="form.can_do" rows="3" placeholder="账款核对&#10;生成对账单" />
      </div>
      <div class="field full">
        <label>不能做 · cannot_do</label>
        <textarea
          v-model="form.cannot_do"
          rows="3"
          placeholder="修改合同金额&#10;承诺减免&#10;对外披露客户名单"
        />
      </div>
      <div class="field full">
        <label>必须请示 · must_ask</label>
        <textarea
          v-model="form.must_ask"
          rows="3"
          placeholder="减免申请&#10;逾期超过 90 天&#10;单笔超过 50 万"
        />
      </div>
      <div class="field full">
        <label>升级路径（每行一级）</label>
        <textarea v-model="form.escalation_path" rows="2" placeholder="直属主管&#10;财务负责人" />
      </div>
    </div>

    <div class="section-label">度量与权限红线</div>
    <div class="form-grid">
      <div class="field full">
        <label>KPI（JSON）</label>
        <textarea v-model="form.kpi" class="mono" rows="4" />
      </div>
      <div class="field full">
        <label>按能力覆盖自主权（JSON）</label>
        <textarea
          v-model="form.autonomy_overrides"
          class="mono"
          rows="3"
          placeholder='{"tool:send_email": "L1", "tool:query_erp": "L3"}'
        />
      </div>
      <div class="field full">
        <label>权限红线（JSON）</label>
        <textarea v-model="form.red_lines" class="mono" rows="8" />
        <span class="help">
          read_only 只读；forbidden_tools 禁用工具；amount_threshold / count_threshold
          超阈值转人工；sandbox_required 沙箱执行。
        </span>
      </div>
    </div>

    <div class="split" style="margin-top: 18px">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        {{ saving ? "保存中…" : contractId ? "保存契约（版本 +1）" : "创建契约" }}
      </button>
      <button class="btn btn-ghost" @click="drawer.close()">取消</button>
    </div>
  </template>
</template>
