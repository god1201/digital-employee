<script setup lang="ts">
import { ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";

const props = defineProps<{ form?: any | null; onSaved?: () => void }>();
const modal = useModalStore();
const toast = useToastStore();

const name = ref(props.form?.name || "");
const code = ref(props.form?.code || "");
const category = ref(props.form?.category || "custom");
const description = ref(props.form?.description || "");
const enabled = ref(String(props.form?.enabled ?? true));
const error = ref("");
const submitting = ref(false);
const fields = ref<any[]>(
  (props.form?.fields || []).map((field: any) => ({
    ...field,
    _optionsText: (field.options || [])
      .map((option: any) =>
        typeof option === "string"
          ? option
          : option.value === option.label
            ? option.value
            : `${option.value}:${option.label}`,
      )
      .join(", "),
  })),
);

const fieldTypes = [
  ["text", "文本"],
  ["textarea", "多行文本"],
  ["number", "数字"],
  ["date", "日期"],
  ["select", "下拉选择"],
  ["user", "用户"],
  ["users", "多用户"],
  ["url", "链接"],
  ["file", "文件链接"],
  ["json", "JSON"],
];

function addField(): void {
  fields.value.push({
    name: `field_${fields.value.length + 1}`,
    label: "新字段",
    type: "text",
    required: false,
    _optionsText: "",
  });
}

function removeField(index: number): void {
  fields.value.splice(index, 1);
}

function move(index: number, offset: number): void {
  const target = index + offset;
  if (target < 0 || target >= fields.value.length) return;
  [fields.value[index], fields.value[target]] = [fields.value[target], fields.value[index]];
}

function buildFields(): any[] {
  return fields.value.map((field) => {
    const item: any = {
      name: String(field.name || "").trim(),
      label: String(field.label || field.name || "").trim(),
      type: field.type,
      required: Boolean(field.required),
    };
    if (!item.name) throw new Error("字段 name 不能为空");
    if (item.type === "select") {
      const options = String(field._optionsText || "")
        .split(/[,，\n]/)
        .map((value) => value.trim())
        .filter(Boolean)
        .map((value) => {
          const idx = value.indexOf(":");
          return idx > 0
            ? { value: value.slice(0, idx).trim(), label: value.slice(idx + 1).trim() }
            : value;
        });
      if (!options.length) throw new Error(`字段「${item.label}」的选项不能为空`);
      item.options = options;
    }
    return item;
  });
}

async function submit(): Promise<void> {
  error.value = "";
  submitting.value = true;
  try {
    const body = {
      name: name.value.trim(),
      code: code.value.trim(),
      category: category.value,
      description: description.value,
      enabled: enabled.value === "true",
      fields: buildFields(),
    };
    if (!body.name || !body.code) throw new Error("请填写表单名称和编码");
    if (props.form) {
      await api.patch(`/approvals/forms/${props.form.id}`, body);
    } else {
      await api.post("/approvals/forms", body);
    }
    toast.push("审批表单已保存");
    modal.close();
    props.onSaved?.();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal" style="width: min(1040px, 96vw)">
    <div class="modal-head">
      <div>
        <h3>{{ form ? "编辑审批表单" : "新建审批表单" }}</h3>
        <p>字段会在发起审批时动态渲染并按类型校验。</p>
      </div>
      <button class="icon-btn" type="button" @click="modal.close()"><AppIcon name="close" /></button>
    </div>
    <form autocomplete="off" @submit.prevent="submit">
      <div class="modal-body">
        <div class="form-grid">
          <div class="field"><label>表单名称</label><input v-model="name" required /></div>
          <div class="field"><label>表单编码</label><input v-model="code" required /></div>
          <div class="field">
            <label>业务分类</label>
            <select v-model="category">
              <option value="finance">财务</option>
              <option value="contract">合同</option>
              <option value="document">文书</option>
              <option value="custom">自定义</option>
            </select>
          </div>
          <div class="field">
            <label>状态</label>
            <select v-model="enabled">
              <option value="true">启用</option>
              <option value="false">停用</option>
            </select>
          </div>
          <div class="field full"><label>表单说明</label><textarea v-model="description" rows="2" /></div>
        </div>

        <div class="section-label">字段定义</div>
        <div class="team-field-head">
          <span>字段 name</span><span>显示名称</span><span>类型</span><span>必填</span><span>选项</span><span></span>
        </div>
        <div class="team-field-row" v-for="(field, index) in fields" :key="index">
          <input v-model="field.name" placeholder="字段 name" />
          <input v-model="field.label" placeholder="显示名称" />
          <select v-model="field.type">
            <option v-for="[value, label] in fieldTypes" :key="value" :value="value">{{ label }}</option>
          </select>
          <select v-model="field.required">
            <option :value="false">选填</option>
            <option :value="true">必填</option>
          </select>
          <input v-model="field._optionsText" placeholder="select 选项：value:label, ..." />
          <div class="node-actions">
            <button type="button" class="icon-btn" :disabled="index === 0" @click="move(index, -1)">↑</button>
            <button type="button" class="icon-btn" :disabled="index === fields.length - 1" @click="move(index, 1)">↓</button>
            <button type="button" class="icon-btn" @click="removeField(index)"><AppIcon name="close" /></button>
          </div>
        </div>
        <button type="button" class="btn btn-sm" style="margin-top: 8px" @click="addField">
          <AppIcon name="plus" />添加字段
        </button>
        <div class="hint-box" style="margin-top: 12px">
          下拉选项格式：<span class="mono">value:显示名</span>，用逗号分隔；也可以只写显示名。
        </div>
        <div class="form-error" :class="{ show: error }">{{ error }}</div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="submitting">
          {{ submitting ? "保存中..." : form ? "保存表单" : "创建表单" }}
        </button>
      </div>
    </form>
  </div>
</template>
