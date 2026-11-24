<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import TeamDetailDrawer from "@/components/TeamDetailDrawer.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Team {
  id: number;
  name: string;
  code: string;
  description?: string;
  status: string;
  member_count: number;
  template_name?: string | null;
  created_at: string;
}

const teams = ref<Team[]>([]);
const drawer = useDrawerStore();
const toast = useToastStore();

const pending = computed(() => teams.value.filter((team) => team.status === "pending_confirmation"));

async function load(): Promise<void> {
  try {
    const data = await api.get<Paged<Team>>("/teams?page_size=100");
    teams.value = data.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载团队失败", "error");
  }
}

function openDetail(row: Team): void {
  drawer.open(TeamDetailDrawer, { teamId: row.id, refresh: load });
}

async function activate(row: Team): Promise<void> {
  try {
    await api.post(`/teams/${row.id}/activate`, {});
    toast.push("团队已启用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "启用失败", "error");
  }
}

async function pause(row: Team): Promise<void> {
  if (!window.confirm("确认暂停该团队？相关员工会被停用。")) return;
  try {
    await api.post(`/teams/${row.id}/pause`, {});
    toast.push("团队已暂停");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "暂停失败", "error");
  }
}

async function disable(row: Team): Promise<void> {
  if (!window.confirm("确认停用该团队？")) return;
  try {
    await api.delete(`/teams/${row.id}`);
    toast.push("团队已停用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "停用失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader eyebrow="organization / teams" title="我的团队" sub="已创建的团队、成员岗位与人机边界。">
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <RouterLink class="btn btn-primary" to="/team-templates">
        <AppIcon name="layers" />从模板创建团队
      </RouterLink>
    </template>
  </PageHeader>

  <div v-if="pending.length" class="alert-banner">
    <div>
      <b>{{ pending.length }}</b> 个团队创建中 · 已生成员工、角色、技能、权限和协作拓扑，等待管理员确认。
    </div>
    <button class="btn btn-sm btn-danger" @click="load">刷新</button>
  </div>

  <div class="panel">
    <DataTable
      :rows="teams"
      :columns="[
        {
          label: '团队',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(row.description || row.code)}</small></div>`,
        },
        { label: '模板', format: (row) => `<span class='tag'>${esc(row.template_name || '自定义')}</span>` },
        { label: '成员', format: (row) => `<span class='mono'>${row.member_count}</span>` },
        { label: '状态', key: 'status' },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有团队，从模板创建一个。"
    >
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openDetail(row)">详情</button>
          <button
            v-if="row.status === 'pending_confirmation'"
            class="btn btn-sm btn-primary"
            @click="activate(row)"
          >
            确认启用
          </button>
          <button v-if="row.status === 'active'" class="btn btn-sm btn-ghost" @click="pause(row)">
            暂停
          </button>
          <button v-if="row.status !== 'disabled'" class="btn btn-sm btn-danger" @click="disable(row)">
            停用
          </button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
