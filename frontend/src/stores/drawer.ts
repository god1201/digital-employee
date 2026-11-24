import { defineStore } from "pinia";
import { ref, shallowRef } from "vue";
import type { Component } from "vue";

export const useDrawerStore = defineStore("drawer", () => {
  const visible = ref(false);
  const component = shallowRef<Component | null>(null);
  const componentProps = ref<Record<string, unknown>>({});

  function open(comp: Component, props: Record<string, unknown> = {}): void {
    component.value = comp;
    componentProps.value = props;
    visible.value = true;
  }

  function close(): void {
    visible.value = false;
    component.value = null;
    componentProps.value = {};
  }

  return { visible, component, componentProps, open, close };
});
