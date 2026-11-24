<script setup lang="ts">
import { reactive } from "vue";

import type { ModalField } from "@/types/ui";

const props = defineProps<{ fields: ModalField[] }>();

const values = reactive<Record<string, any>>({});

function normalizedOptions(field: ModalField) {
  return (field.options || []).map((option) =>
    typeof option === "string" ? { value: option, label: option } : option,
  );
}

function inputType(field: ModalField): string {
  if (field.type === "number") return "number";
  if (field.type === "date") return "date";
  if (field.type === "password") return "password";
  return "text";
}

function initialize(): void {
  for (const field of props.fields) {
    if (field.type === "multiselect") {
      values[field.name] = Array.isArray(field.value) ? [...field.value] : [];
    } else if (field.type === "json") {
      values[field.name] =
        typeof field.value === "string"
          ? field.value
          : JSON.stringify(field.value ?? {}, null, 2);
    } else if (field.type === "select") {
      const options = normalizedOptions(field);
      const current = field.value ?? "";
      const matched = options.some((option) => String(option.value) === String(current));
      values[field.name] = matched ? current : (options[0]?.value ?? "");
    } else {
      values[field.name] = field.value ?? "";
    }
  }
}
initialize();

function isEmpty(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

function getValues(): Record<string, any> {
  const result: Record<string, any> = {};
  for (const field of props.fields) {
    let value = values[field.name];
    if (isEmpty(value)) {
      if (field.required) throw new Error(`请填写「${field.label}」`);
      continue;
    }
    if (field.type === "json") {
      try {
        value = typeof value === "string" ? JSON.parse(value) : value;
      } catch {
        throw new Error(`「${field.label}」不是合法 JSON`);
      }
    } else if (field.type === "number") {
      value = Number(value);
    } else if (field.type === "multiselect") {
      value = (value as any[]).map((item) => (field.numeric ? Number(item) : item));
      if (field.required && !value.length) throw new Error(`请选择「${field.label}」`);
    } else if (field.type === "select" && field.numeric) {
      value = Number(value);
    }
    result[field.name] = value;
  }
  return result;
}

defineExpose({ getValues });
</script>

<template>
  <div class="form-grid">
    <div
      v-for="field in fields"
      :key="field.name"
      class="field"
      :class="{ full: field.full || field.type === 'textarea' || field.type === 'json' }"
    >
      <label>
        {{ field.label }}
        <span v-if="field.required" style="color: var(--coral)">*</span>
      </label>

      <select
        v-if="field.type === 'select'"
        v-model="values[field.name]"
        :name="field.name"
        :required="field.required"
      >
        <option v-for="option in normalizedOptions(field)" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <select
        v-else-if="field.type === 'multiselect'"
        v-model="values[field.name]"
        :name="field.name"
        multiple
        :size="field.size || 5"
        :required="field.required"
      >
        <option v-for="option in normalizedOptions(field)" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <textarea
        v-else-if="field.type === 'textarea' || field.type === 'json'"
        v-model="values[field.name]"
        :name="field.name"
        :rows="field.rows || 4"
        :placeholder="field.placeholder || ''"
        :required="field.required"
      />

      <input
        v-else
        v-model="values[field.name]"
        :name="field.name"
        :type="inputType(field)"
        :step="field.step || (field.type === 'number' ? 'any' : undefined)"
        :placeholder="field.placeholder || ''"
        :required="field.required"
      />

      <span v-if="field.help" class="help">{{ field.help }}</span>
    </div>
  </div>
</template>
