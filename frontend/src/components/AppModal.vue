<script setup lang="ts">
import { ref } from "vue";

import { useModalStore } from "@/stores/modal";
import AppIcon from "./AppIcon.vue";
import SchemaForm from "./SchemaForm.vue";

const modal = useModalStore();
const formRef = ref<InstanceType<typeof SchemaForm> | null>(null);
const error = ref("");
const submitting = ref(false);

async function submit(): Promise<void> {
  if (!modal.onSubmit) return;
  error.value = "";
  submitting.value = true;
  try {
    const values = formRef.value?.getValues() || {};
    await modal.onSubmit(values);
    modal.close();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div v-if="modal.visible" class="backdrop" @click.self="modal.close()">
    <component
      :is="modal.component"
      v-if="modal.component"
      v-bind="modal.componentProps"
    />
    <div v-else class="modal" :class="{ wide: modal.wide }">
      <div class="modal-head">
        <div>
          <h3>{{ modal.title }}</h3>
          <p v-if="modal.sub">{{ modal.sub }}</p>
        </div>
        <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
          <AppIcon name="close" />
        </button>
      </div>
      <form autocomplete="off" @submit.prevent="submit">
        <div class="modal-body">
          <SchemaForm ref="formRef" :fields="modal.fields" />
          <div class="form-error" :class="{ show: error }">{{ error }}</div>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="submitting">
            {{ submitting ? "处理中..." : modal.submitLabel }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
