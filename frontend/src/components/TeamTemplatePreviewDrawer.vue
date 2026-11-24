<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { esc } from "@/utils/format";

interface TemplateRole {
  code?: string;
  name?: string;
  description?: string;
  skills?: string[];
  tools?: string[];
  approval_threshold?: string;
  sandbox?: string;
}

interface TeamTemplateLike {
  id: number;
  name: string;
  description?: string;
  category?: string;
  roles?: TemplateRole[];
  topology?: { edges?: Array<{ from: string; to: string }> };
  tags?: string[];
}

const props = defineProps<{
  template: TeamTemplateLike;
  useTemplate?: (id: number) => void;
}>();

const drawer = useDrawerStore();

const topologyLines = computed<string[]>(() => {
  const names: Record<string, string> = {};
  for (const role of props.template.roles || []) {
    if (role.code) names[role.code] = role.name || role.code;
  }
  return (props.template.topology?.edges || []).map(
    (edge) => `${names[edge.from] || edge.from} → ${names[edge.to] || edge.to}`,
  );
});

function use(): void {
  props.useTemplate?.(props.template.id);
}
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ template.name }}</h3>
      <p>{{ template.category || "通用" }} · {{ (template.roles || []).length }} 个岗位</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <p class="muted" style="font-size: 12px; line-height: 1.7">{{ template.description }}</p>

  <div class="section-label">岗位组合</div>
  <DataTable
    :rows="template.roles || []"
    :columns="[
      { label: '角色', format: (row) => esc(row.name || row.code) },
      { label: 'Skills', format: (row) => `<span class='mono dim'>${esc((row.skills || []).join(' ; '))}</span>` },
      { label: '工具组', format: (row) => esc((row.tools || []).join(' · ')) },
      { label: '审批', key: 'approval' },
    ]"
    empty-text="模板没有岗位"
  >
    <template #cell-approval="{ row }">
      <StatusPill :status="row.approval_threshold" />
    </template>
  </DataTable>

  <div class="section-label">协作拓扑</div>
  <div class="hint-box">
    <template v-if="topologyLines.length">
      <div v-for="(line, index) in topologyLines" :key="index">{{ line }}</div>
    </template>
    <template v-else>扁平团队</template>
  </div>

  <div style="margin-top: 16px">
    <button class="btn btn-primary" type="button" @click="use">使用此模板</button>
  </div>
</template>
