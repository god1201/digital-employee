import { defineStore } from "pinia";
import { ref, shallowRef } from "vue";
import type { Component } from "vue";

import type { FormModalOptions, ModalField } from "@/types/ui";

export const useModalStore = defineStore("modal", () => {
  const visible = ref(false);
  const title = ref("");
  const sub = ref("");
  const wide = ref(false);
  const fields = ref<ModalField[]>([]);
  const submitLabel = ref("保存");
  const onSubmit = ref<FormModalOptions["onSubmit"] | null>(null);
  const component = shallowRef<Component | null>(null);
  const componentProps = ref<Record<string, unknown>>({});

  function reset(): void {
    visible.value = false;
    title.value = "";
    sub.value = "";
    wide.value = false;
    fields.value = [];
    submitLabel.value = "保存";
    onSubmit.value = null;
    component.value = null;
    componentProps.value = {};
  }

  function openForm(options: FormModalOptions): void {
    reset();
    title.value = options.title;
    sub.value = options.sub || "";
    wide.value = options.wide || false;
    fields.value = options.fields;
    submitLabel.value = options.submitLabel || "保存";
    onSubmit.value = options.onSubmit;
    visible.value = true;
  }

  function openCustom(comp: Component, props: Record<string, unknown> = {}): void {
    reset();
    component.value = comp;
    componentProps.value = props;
    visible.value = true;
  }

  function close(): void {
    reset();
  }

  return {
    visible,
    title,
    sub,
    wide,
    fields,
    submitLabel,
    onSubmit,
    component,
    componentProps,
    openForm,
    openCustom,
    close,
  };
});
