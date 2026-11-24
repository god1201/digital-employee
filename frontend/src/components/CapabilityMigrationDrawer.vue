<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

const props = defineProps<{
  employee: Employee;
  onChanged?: () => void;
}>();

const employees = ref<Employee[]>([]);
const sourceId = ref<number | "">("");
const components = ref<string[]>(["skills", "artifacts", "preferences"]);
const report = ref<any>(null);
const saving = ref(false);
const dryRun = ref(true);

const drawer = useDrawerStore();
const toast = useToastStore();

const componentOptions = [
  { value: "skills", label: "技能装配" },
  { value: "artifacts", label: "生效/已审批学习工件" },
  { value: "preferences", label: "偏好记忆" },
  { value: "contract", label: "岗位契约（草稿）" },
];

const sourceOptions = computed(() =>
  employees.value.filter((item) => item.id !== props.employee.id),
);

async function load(): Promise<void> {
  try {
    const data = await api.get<any>("/digital-employees?page_size=200");
    employees.value = data.items;
    if (sourceOptions.value.length) sourceId.value = sourceOptions.value[0].id;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function toggle(value: string): void {
  if (components.value.includes(value)) {
    components.value = components.value.filter((item) => item !== value);
  } else {
    components.value = [...components.value, value];
  }
}

async function migrate(dry: boolean): Promise<void> {
  if (!sourceId.value) {
    toast.push("请选择源员工", "error");
    return;
  }
  if (!components.value.length) {
    toast.push("至少选择一个迁移项", "error");
    return;
  }
  saving.value = true;
  dryRun.value = dry;
  try {
    const result = await api.post<any>("/capability-migrations", {
      source_employee_id: sourceId.value,
      target_employee_id: props.employee.id,
      components: components.value,
      dry_run: dry,
    });
    report.value = result;
    toast.push(dry ? "预览完成，未写入数据" : `迁移完成：${result.status}`);
    if (!dry) props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "迁移失败", "error");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee.name }} · 能力迁移</h3>
      <p>{{ employee.code }} · 从其他员工复制可复用能力</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="section-label">源员工</div>
  <select v-model="sourceId" class="input">
    <option v-for="item in sourceOptions" :key="item.id" :value="item.id">
      {{ item.name }} · {{ item.code }}
    </option>
  </select>

  <div class="section-label">迁移项</div>
  <label v-for="item in componentOptions" :key="item.value" class="check-row">
    <input
      type="checkbox"
      :checked="components.includes(item.value)"
      @change="toggle(item.value)"
    />
    <span>{{ item.label }}</span>
  </label>

  <div class="alert-banner" style="margin-top: 14px">
    <div>
      技能会解析依赖并检测冲突；学习工件与契约以“待审批/草稿”方式复制，不会直接生效。
    </div>
  </div>

  <div class="split" style="margin-top: 16px">
    <button class="btn btn-ghost" :disabled="saving" @click="migrate(true)">预览迁移</button>
    <button class="btn btn-primary" :disabled="saving" @click="migrate(false)">
      {{ saving ? "处理中…" : "执行迁移" }}
    </button>
  </div>

  <template v-if="report">
    <div class="section-label">迁移结果</div>
    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="report.status" /></b></div>
      <div class="meta"><span>模式</span><b>{{ report.dry_run ? "预览" : "已执行" }}</b></div>
      <div class="meta"><span>时间</span><b>{{ fmtDate(report.created_at) }}</b></div>
    </div>
    <JsonBlock :value="report.report" />
  </template>
</template>

<style scoped>
.input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
}
.check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 12.5px;
  color: var(--muted);
}
</style>
