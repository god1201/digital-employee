<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import RolePresetDrawer from "@/components/RolePresetDrawer.vue";
import StatusPill from "@/components/StatusPill.vue";
import TeamTemplatePreviewDrawer from "@/components/TeamTemplatePreviewDrawer.vue";
import TeamWizardModal from "@/components/TeamWizardModal.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
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

interface TeamTemplate {
  id: number;
  code: string;
  name: string;
  description?: string;
  category?: string;
  roles?: TemplateRole[];
  topology?: { mode?: string; edges?: Array<{ from: string; to: string }> };
  tags?: string[];
  is_builtin?: boolean;
}

interface RolePreset {
  id: number;
  code: string;
  name: string;
  description?: string;
  default_skills?: string[];
  tool_groups?: string[];
  approval_threshold: string;
  sandbox: string;
  status: string;
  is_builtin: boolean;
}

const templates = ref<TeamTemplate[]>([]);
const presets = ref<RolePreset[]>([]);
const selectedPresetId = ref<number | null>(null);
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

const selectedPreset = computed<RolePreset | null>(
  () =>
    presets.value.find((item) => item.id === selectedPresetId.value) ||
    presets.value[0] ||
    null,
);

const badgeId = computed(() =>
  selectedPreset.value ? `DE-${String(selectedPreset.value.id).padStart(4, "0")}` : "",
);

const metrics = computed(() => {
  const preset = selectedPreset.value;
  if (!preset) return [];
  const approvalMap: Record<string, number> = { low: 35, medium: 60, high: 85, dual: 95 };
  return [
    { label: "技能覆盖", value: Math.min((preset.default_skills || []).length * 20, 100), cls: "blue" },
    { label: "工具覆盖", value: Math.min((preset.tool_groups || []).length * 20, 100), cls: "mint" },
    { label: "审批强度", value: approvalMap[preset.approval_threshold] ?? 60, cls: "amber" },
  ];
});

async function load(): Promise<void> {
  try {
    const [templateData, presetData] = await Promise.all([
      api.get<Paged<TeamTemplate>>("/team-templates"),
      api.get<Paged<RolePreset>>("/role-presets"),
    ]);
    templates.value = templateData.items;
    presets.value = presetData.items;
    if (
      selectedPresetId.value === null ||
      !presets.value.some((item) => item.id === selectedPresetId.value)
    ) {
      selectedPresetId.value = presets.value[0]?.id ?? null;
    }
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载团队模板失败", "error");
  }
}

function openWizard(templateId?: number | null): void {
  if (!templates.value.length) {
    toast.push("没有可用团队模板", "error");
    return;
  }
  modal.openCustom(TeamWizardModal, {
    templates: templates.value,
    initialTemplateId: templateId ?? null,
  });
}

function previewTemplate(template: TeamTemplate): void {
  drawer.open(TeamTemplatePreviewDrawer, {
    template,
    useTemplate: (id: number) => {
      drawer.close();
      openWizard(id);
    },
  });
}

function selectPreset(preset: RolePreset): void {
  selectedPresetId.value = preset.id;
}

function openPreset(preset: RolePreset): void {
  drawer.open(RolePresetDrawer, { preset });
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="organization / templates"
    title="团队模板"
    sub="一键创建岗位组合、权限边界、SOP 和协作拓扑，降低多数字员工组建成本。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="openWizard(null)"><AppIcon name="plus" />从模板创建团队</button>
    </template>
  </PageHeader>

  <div class="template-grid">
    <div v-for="item in templates" :key="item.id" class="template-card">
      <div class="template-top">
        <span class="tag">{{ item.category || "通用" }}</span>
        <span class="dim mono">{{ (item.roles || []).length }} 岗位</span>
      </div>
      <h3>{{ item.name }}</h3>
      <p>{{ item.description }}</p>
      <div class="tags">
        <span v-for="tag in item.tags || []" :key="tag" class="tag">{{ tag }}</span>
      </div>
      <div class="card-foot">
        <button class="btn btn-primary btn-sm" @click="openWizard(item.id)">使用模板</button>
        <button class="btn btn-sm btn-ghost" @click="previewTemplate(item)">预览拓扑</button>
      </div>
    </div>
    <div v-if="!templates.length" class="empty">没有可用模板</div>
  </div>

  <div class="team-layout">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">角色预设库</div>
          <div class="panel-sub">{{ presets.length }} 个岗位</div>
        </div>
      </div>
      <DataTable
        :rows="presets"
        :columns="[
          {
            label: '角色',
            format: (row) =>
              `<div class='cell-main' style='min-width:150px'><b>${esc(row.name)}</b><small>${esc(row.description || '')}</small></div>`,
          },
          {
            label: '默认 SKILL',
            format: (row) =>
              `<span class='mono dim'>${esc((row.default_skills || []).join(' ; '))}</span>`,
          },
          { label: '工具组', format: (row) => esc((row.tool_groups || []).join(' · ')) },
          { label: '审批', key: 'approval' },
          { label: '沙盒', format: (row) => `<span class='tag'>${esc(row.sandbox)}</span>` },
          { label: '', key: 'actions' },
        ]"
        empty-text="还没有角色预设"
      >
        <template #cell-approval="{ row }">
          <StatusPill :status="row.approval_threshold" />
        </template>
        <template #cell-actions="{ row }">
          <div class="row-actions">
            <button class="btn btn-sm btn-ghost" @click="selectPreset(row)">工牌</button>
            <button class="btn btn-sm" @click="openPreset(row)">详情</button>
          </div>
        </template>
      </DataTable>
    </div>

    <div id="role-badge">
      <div v-if="selectedPreset" class="role-badge">
        <div class="badge-head">
          <div>
            <div class="panel-title">员工工牌</div>
            <div class="panel-sub">角色预设 · {{ selectedPreset.code }}</div>
          </div>
          <span class="tag">{{ selectedPreset.is_builtin ? "BUILT-IN" : "CUSTOM" }}</span>
        </div>
        <div class="badge-id">{{ badgeId }}</div>
        <h3>{{ selectedPreset.name }}</h3>
        <p class="muted">{{ selectedPreset.description || "" }}</p>
        <div class="metrics">
          <div v-for="metric in metrics" :key="metric.label" class="metric-row">
            <span>{{ metric.label }}</span>
            <div class="metric-bar">
              <div class="metric-fill" :class="metric.cls" :style="{ width: `${metric.value}%` }" />
            </div>
            <b>{{ metric.value }}</b>
          </div>
        </div>
        <div class="badge-tags">
          <span class="tag">{{ selectedPreset.approval_threshold }} 审批</span>
          <span class="tag">{{ selectedPreset.sandbox }} 沙盒</span>
          <span class="tag">{{ (selectedPreset.default_skills || []).length }} Skills</span>
          <span class="tag">{{ (selectedPreset.tool_groups || []).length }} 工具组</span>
        </div>
        <div class="badge-actions">
          <button class="btn" @click="openPreset(selectedPreset)">查看完整画像</button>
        </div>
      </div>
      <EmptyState v-else text="选择一个角色查看工牌" />
    </div>
  </div>
</template>
