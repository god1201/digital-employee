import { defineStore } from "pinia";
import { ref } from "vue";

export interface SelectedEmployee {
  id: number;
  name: string;
  code: string;
  position?: string | null;
  status?: string;
  agent_id?: number | null;
}

export const useEmployeeStore = defineStore("employee", () => {
  const selected = ref<SelectedEmployee | null>(null);
  const summary = ref<Record<string, any> | null>(null);

  function select(employee: SelectedEmployee, workbench?: Record<string, any>): void {
    selected.value = employee;
    summary.value = workbench || null;
  }

  function updateSummary(workbench: Record<string, any>): void {
    summary.value = workbench;
  }

  function clear(): void {
    selected.value = null;
    summary.value = null;
  }

  return { selected, summary, select, updateSummary, clear };
});
