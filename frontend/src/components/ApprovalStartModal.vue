<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { approvalCategoryLabel } from "@/utils/approval";

const props = defineProps<{
  flows: any[];
  forms: any[];
  users: any[];
  employees: any[];
  selectedFlowId?: number | null;
  onCreated?: () => void;
}>();

const modal = useModalStore();
const toast = useToastStore();
const error = ref("");
const submitting = ref(false);

const enabledFlows = computed(() => props.flows.filter((flow) => flow.enabled));
const flowId = ref<number>(
  Number(props.selectedFlowId) ||
    enabledFlows.value.find((flow) => flow.category === "finance" && flow.form_id)?.id ||
    enabledFlows.value.find((flow) => flow.form_id)?.id ||
    enabledFlows.value[0]?.id ||
    0,
);
const title = ref("");
const employeeId = ref<number | "">("");
const businessRef = ref("");
const priority = ref(100);
const formData = reactive<Record<string, any>>({});

const selectedFlow = computed(() => enabledFlows.value.find((flow) => flow.id === Number(flowId.value)));
const formFields = computed(() => {
  const form = props.forms.find((item) => item.id === selectedFlow.value?.form_id);
  return form?.fields || [];
});

function resetFormData(): void {
  for (const key of Object.keys(formData)) delete formData[key];
  for (const field of formFields.value) {
    if (field.type === "multiselect" || field.type === "users") formData[field.name] = [];
    else if (field.type === "json") {
      formData[field.name] =
        typeof field.default === "string"
          ? field.default
          : JSON.stringify(field.default ?? {}, null, 2);
    } else if (field.type === "select") {
      const opts = options(field);
      const current = field.default ?? "";
      const matched = opts.some((option) => String(option.value) === String(current));
      formData[field.name] = matched ? current : (opts[0]?.value ?? "");
    } else formData[field.name] = field.default ?? "";
  }
}

watch(flowId, resetFormData, { immediate: true });

function options(field: any): Array<{ value: any; label: string }> {
  return (field.options || []).map((option: any) =>
    typeof option === "string" ? { value: option, label: option } : option,
  );
}

function isEmpty(value: any): boolean {
  return value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length);
}

function buildFormData(): Record<string, any> {
  const result: Record<string, any> = {};
  for (const field of formFields.value) {
    let value = formData[field.name];
    if (isEmpty(value)) {
      if (field.required) throw new Error(`请填写「${field.label}」`);
      continue;
    }
    if (field.type === "number") value = Number(value);
    else if (field.type === "user") value = Number(value);
    else if (field.type === "users") value = (value as any[]).map(Number);
    else if (field.type === "json") {
      try {
        value = typeof value === "string" ? JSON.parse(value) : value;
      } catch {
        throw new Error(`「${field.label}」不是合法 JSON`);
      }
    }
    result[field.name] = value;
  }
  return result;
}

async function submit(): Promise<void> {
  error.value = "";
  submitting.value = true;
  try {
    if (!title.value.trim()) throw new Error("请填写审批标题");
    await api.post("/approvals/instances", {
      flow_id: Number(flowId.value),
      title: title.value.trim(),
      form_data: buildFormData(),
      employee_id: employeeId.value ? Number(employeeId.value) : null,
      business_ref: businessRef.value || null,
      priority: Number(priority.value) || 100,
    });
    toast.push("审批已提交");
    modal.close();
    props.onCreated?.();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "提交失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal" style="width: min(980px, 96vw)">
    <div class="modal-head">
      <div>
        <h3>发起审批</h3>
        <p>选择流程并填写表单；提交后按节点顺序流转。</p>
      </div>
      <button class="icon-btn" type="button" @click="modal.close()"><AppIcon name="close" /></button>
    </div>
    <form autocomplete="off" @submit.prevent="submit">
      <div class="modal-body">
        <div class="form-grid">
          <div class="field">
            <label>审批流程</label>
            <select v-model="flowId">
              <option v-for="flow in enabledFlows" :key="flow.id" :value="flow.id">
                {{ flow.name }} · {{ approvalCategoryLabel(flow.category) }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>审批标题</label>
            <input v-model="title" required :placeholder="`${selectedFlow?.name || '审批'} · ${new Date().toLocaleDateString('zh-CN')}`" />
          </div>
          <div class="field">
            <label>关联数字员工（可选）</label>
            <select v-model="employeeId">
              <option value="">不关联</option>
              <option v-for="employee in employees" :key="employee.id" :value="employee.id">
                {{ employee.name }} · {{ employee.code }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>业务编号（可选）</label>
            <input v-model="businessRef" placeholder="例如：FIN-2026-001" />
          </div>
          <div class="field">
            <label>优先级</label>
            <input v-model.number="priority" type="number" min="0" max="1000" />
          </div>
        </div>

        <div class="section-label">表单内容</div>
        <div v-if="formFields.length" class="form-grid">
          <div
            v-for="field in formFields"
            :key="field.name"
            class="field"
            :class="{ full: ['textarea', 'json'].includes(field.type) }"
          >
            <label>
              {{ field.label }}
              <span v-if="field.required" style="color: var(--coral)">*</span>
            </label>

            <select v-if="field.type === 'select'" v-model="formData[field.name]" :required="field.required">
              <option v-for="option in options(field)" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>

            <select
              v-else-if="field.type === 'user'"
              v-model="formData[field.name]"
              :required="field.required"
            >
              <option value="">请选择</option>
              <option v-for="user in users" :key="user.id" :value="user.id">
                {{ user.full_name || user.username }}
              </option>
            </select>

            <select
              v-else-if="field.type === 'users'"
              v-model="formData[field.name]"
              multiple
              size="4"
              :required="field.required"
            >
              <option v-for="user in users" :key="user.id" :value="user.id">
                {{ user.full_name || user.username }}
              </option>
            </select>

            <textarea
              v-else-if="['textarea', 'json'].includes(field.type)"
              v-model="formData[field.name]"
              :rows="field.type === 'json' ? 4 : 3"
              :placeholder="field.placeholder || ''"
              :required="field.required"
            />

            <input
              v-else
              v-model="formData[field.name]"
              :type="field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'"
              :placeholder="field.placeholder || ''"
              :required="field.required"
            />
            <span v-if="field.help" class="help">{{ field.help }}</span>
          </div>
        </div>
        <div v-else class="hint-box">该流程没有绑定表单，可直接提交。</div>

        <div class="form-error" :class="{ show: error }">{{ error }}</div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="submitting">
          {{ submitting ? "提交中..." : "提交审批" }}
        </button>
      </div>
    </form>
  </div>
</template>
