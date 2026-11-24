import { defineStore } from "pinia";
import { ref } from "vue";

export interface ToastItem {
  id: number;
  message: string;
  type: "success" | "error" | "info";
}

let nextId = 1;

export const useToastStore = defineStore("toast", () => {
  const items = ref<ToastItem[]>([]);

  function remove(id: number): void {
    items.value = items.value.filter((item) => item.id !== id);
  }

  function push(message: string, type: ToastItem["type"] = "success"): void {
    const item: ToastItem = { id: nextId++, message, type };
    items.value.push(item);
    window.setTimeout(() => remove(item.id), 3600);
  }

  return { items, push, remove };
});
