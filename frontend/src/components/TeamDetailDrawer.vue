<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface TeamMember {
  id: number;
  role_code: string;
  role_name: string;
  employee_name?: string | null;
  employee_code?: string | null;
  skills: string[];
  tools: string[];
  approval_threshold: string;
  sandbox: string;
  status: string;
}

interface TeamTopology {
  mode?: string;
  edges?: Array<{ from: string; to: string }>;
}

interface TeamDetail {
  id: number;
  name: string;
  code: string;
  status: string;
  template_name?: string | null;
  topology?: TeamTopology;
  members?: TeamMember[];
  created_at: string;
}

const props = defineProps<{
  teamId: number;
  refresh?: () => void;
}>();

const drawer = useDrawerStore();
const toast = useToastStore();
const team = ref<TeamDetail | null>(null);
const loading = ref(true);

const topologyLines = computed<string[]>(() => {
  const data = team.value;
  if (!data) return [];
  const names: Record<string, string> = {};
  for (const member of data.members || []) {
    names[member.role_code] = member.role_name;
  }
  return (data.topology?.edges || []).map(
    (edge) => `${names[edge.from] || edge.from} → ${names[edge.to] || edge.to}`,
  );
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    team.value = await api.get<TeamDetail>(`/teams/${props.teamId}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载团队详情失败", "error");
  } finally {
    loading.value = false;
  }
}

function done(message: string): void {
  toast.push(message);
  drawer.close();
  props.refresh?.();
}

async function activate(): Promise<void> {
  try {
    await api.post(`/teams/${props.teamId}/activate`, {});
    done("团队已启用");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "启用失败", "error");
  }
}

async function pause(): Promise<void> {
  if (!window.confirm("确认暂停该团队？相关员工会被停用。")) return;
  try {
    await api.post(`/teams/${props.teamId}/pause`, {});
    done("团队已暂停");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "暂停失败", "error");
  }
}

async function disable(): Promise<void> {
  if (!window.confirm("确认停用该团队？")) return;
  try {
    await api.delete(`/teams/${props.teamId}`);
    done("团队已停用");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "停用失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ team?.name || "团队详情" }}</h3>
      <p v-if="team">{{ team.template_name || "自定义团队" }} · {{ team.code }}</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="loading" class="skeleton" />
  <div v-else-if="!team" class="empty">团队不存在或已删除</div>
  <template v-else>
    <div class="meta-grid">
      <div class="meta">
        <span>状态</span>
        <b><StatusPill :status="team.status" /></b>
      </div>
      <div class="meta">
        <span>成员</span>
        <b>{{ (team.members || []).length }}</b>
      </div>
      <div class="meta">
        <span>模板</span>
        <b>{{ team.template_name || "自定义" }}</b>
      </div>
      <div class="meta">
        <span>创建</span>
        <b>{{ fmtDate(team.created_at) }}</b>
      </div>
    </div>

    <div v-if="team.status === 'pending_confirmation'" class="alert-banner">
      <div><b>团队创建中</b> · 已生成员工、角色、技能、权限和协作拓扑，等待管理员确认。</div>
      <button class="btn btn-sm btn-primary" type="button" @click="activate">确认启用</button>
    </div>

    <div class="section-label">协作拓扑</div>
    <div class="hint-box">
      <template v-if="topologyLines.length">
        <div v-for="(line, index) in topologyLines" :key="index">{{ line }}</div>
      </template>
      <template v-else>扁平团队</template>
    </div>

    <div class="section-label">成员</div>
    <DataTable
      :rows="team.members || []"
      :columns="[
        {
          label: '角色',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.role_name)}</b><small>${esc(row.role_code)}</small></div>`,
        },
        {
          label: '员工',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.employee_name || '—')}</b><small class='mono'>${esc(row.employee_code || '')}</small></div>`,
        },
        { label: 'Skills', format: (row) => `<span class='dim mono'>${esc((row.skills || []).join(' ; '))}</span>` },
        { label: '工具组', format: (row) => esc((row.tools || []).join(' · ')) },
        { label: '审批', key: 'approval' },
        { label: '沙盒', format: (row) => `<span class='tag'>${esc(row.sandbox)}</span>` },
        { label: '状态', key: 'status' },
      ]"
      empty-text="没有成员"
    >
      <template #cell-approval="{ row }">
        <StatusPill :status="row.approval_threshold" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
    </DataTable>

    <div class="section-label">操作</div>
    <div class="row-actions">
      <button
        v-if="team.status === 'pending_confirmation'"
        class="btn btn-primary"
        type="button"
        @click="activate"
      >
        确认启用
      </button>
      <button v-if="team.status === 'active'" class="btn btn-ghost" type="button" @click="pause">
        暂停
      </button>
      <button v-if="team.status !== 'disabled'" class="btn btn-danger" type="button" @click="disable">
        停用
      </button>
    </div>
  </template>
</template>
