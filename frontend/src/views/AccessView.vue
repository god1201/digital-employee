<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Authorization {
  id: number;
  system_name: string;
  system_code: string;
  base_url?: string | null;
  access_type: string;
  has_credential: boolean;
  expires_at?: string | null;
  status: string;
}

interface AccessRule {
  id: number;
  path_pattern: string;
  method: string;
  effect: string;
  priority: number;
  system_code?: string | null;
  enabled: boolean;
}

type TabKey = "authorizations" | "rules";

const authorizations = ref<Authorization[]>([]);
const rules = ref<AccessRule[]>([]);
const activeTab = ref<TabKey>("authorizations");
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [authData, ruleData] = await Promise.all([
      api.get<Paged<Authorization>>("/authorizations?page_size=200"),
      api.get<Paged<AccessRule>>("/access-rules?page_size=200"),
    ]);
    authorizations.value = authData.items;
    rules.value = ruleData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载授权与准入数据失败", "error");
  }
}

function createAuthorization(): void {
  modal.openForm({
    title: "新增授权",
    sub: "凭证会使用 Fernet 加密后存储。",
    fields: [
      { name: "system_name", label: "系统名称", required: true, placeholder: "CRM" },
      { name: "system_code", label: "系统编码", required: true, placeholder: "crm" },
      { name: "base_url", label: "Base URL", placeholder: "https://crm.example.com" },
      {
        name: "access_type",
        label: "访问方式",
        type: "select",
        options: ["api_key", "token", "oauth2", "cookie", "login"],
      },
      { name: "username", label: "账号" },
      { name: "credential", label: "凭证 / Token", type: "password" },
      { name: "description", label: "说明", full: true, type: "textarea", rows: 2 },
    ],
    submitLabel: "保存授权",
    onSubmit: async (values) => {
      await api.post("/authorizations", values);
      toast.push("授权已保存");
      await load();
    },
  });
}

function createRule(): void {
  modal.openForm({
    title: "新增准入规则",
    sub: "未匹配到 allow 时默认拒绝。",
    fields: [
      { name: "path_pattern", label: "路径模式", required: true, placeholder: "/user/**" },
      { name: "effect", label: "效果", type: "select", options: ["allow", "deny"], value: "allow" },
      { name: "priority", label: "优先级", type: "number", value: 100 },
      { name: "method", label: "HTTP 方法", placeholder: "* 或 GET" },
      { name: "system_code", label: "系统编码", placeholder: "留空表示全部" },
      { name: "description", label: "说明", full: true, type: "textarea", rows: 2 },
    ],
    submitLabel: "保存规则",
    onSubmit: async (values) => {
      await api.post("/access-rules", {
        path_pattern: values.path_pattern,
        effect: values.effect,
        priority: Number(values.priority || 100),
        method: values.method || "*",
        system_code: values.system_code || null,
        description: values.description,
      });
      toast.push("准入规则已保存");
      await load();
    },
  });
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="governance / access"
    title="授权与准入"
    sub="凭证加密存储；路径级规则默认拒绝。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn" @click="createAuthorization"><AppIcon name="plus" />新增授权</button>
      <button class="btn btn-primary" @click="createRule"><AppIcon name="plus" />新增规则</button>
    </template>
  </PageHeader>

  <div class="tabs">
    <button class="tab" :class="{ active: activeTab === 'authorizations' }" @click="activeTab = 'authorizations'">
      授权记录（{{ authorizations.length }}）
    </button>
    <button class="tab" :class="{ active: activeTab === 'rules' }" @click="activeTab = 'rules'">
      准入规则（{{ rules.length }}）
    </button>
  </div>

  <div v-show="activeTab === 'authorizations'" class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">授权记录</div>
        <div class="panel-sub">外部系统凭证，响应不回传密文</div>
      </div>
    </div>
    <DataTable
      :rows="authorizations"
      :columns="[
        {
          label: '系统',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.system_name)}</b><small class='mono'>${esc(row.system_code)}</small></div>`,
        },
        { label: '方式', format: (row) => `<span class='tag'>${esc(row.access_type)}</span>` },
        { label: 'Base URL', format: (row) => `<span class='mono dim'>${esc(row.base_url || '—')}</span>` },
        { label: '凭证', key: 'credential' },
        { label: '过期', format: (row) => `<span class='muted'>${fmtDate(row.expires_at)}</span>` },
        { label: '状态', key: 'status' },
      ]"
      empty-text="还没有授权记录"
    >
      <template #cell-credential="{ row }">
        <StatusPill :status="row.has_credential ? 'active' : 'disabled'" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.status" />
      </template>
    </DataTable>
  </div>

  <div v-show="activeTab === 'rules'" class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">准入规则</div>
        <div class="panel-sub">优先级越高越先匹配；同级 deny 胜出</div>
      </div>
    </div>
    <DataTable
      :rows="rules"
      :columns="[
        { label: '路径', format: (row) => `<span class='mono'>${esc(row.path_pattern)}</span>` },
        { label: '方法', format: (row) => `<span class='mono'>${esc(row.method)}</span>` },
        { label: '效果', key: 'effect' },
        { label: '优先级', format: (row) => `<span class='mono'>${row.priority}</span>` },
        { label: '系统', format: (row) => `<span class='muted'>${esc(row.system_code || '全部')}</span>` },
        { label: '状态', key: 'status' },
      ]"
      empty-text="还没有准入规则"
    >
      <template #cell-effect="{ row }">
        <StatusPill :status="row.effect === 'deny' ? 'block' : 'allow'" :text="row.effect" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.enabled ? 'active' : 'disabled'" />
      </template>
    </DataTable>
  </div>
</template>
