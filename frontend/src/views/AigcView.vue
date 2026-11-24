<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AigcAssetDrawer from "@/components/AigcAssetDrawer.vue";
import AigcAssetGrid from "@/components/AigcAssetGrid.vue";
import AigcJobDrawer from "@/components/AigcJobDrawer.vue";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatCard from "@/components/StatCard.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate, fmtMs } from "@/utils/format";

const typeLabels: Record<string, string> = {
  text_to_image: "文生图",
  text_to_video: "文生视频",
  image_to_video: "图生视频",
};
const providerLabels: Record<string, string> = {
  mock: "内置 Mock",
  openai_image: "OpenAI 兼容图片",
  comfyui: "ComfyUI",
  http_generic: "通用 HTTP",
};
const tab = ref<"jobs" | "assets" | "templates" | "providers" | "stats">("jobs");
const stats = ref<any>({});
const providers = ref<any[]>([]);
const templates = ref<any[]>([]);
const jobs = ref<any[]>([]);
const assets = ref<any[]>([]);
const employees = ref<any[]>([]);
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

const totals = computed(() => stats.value.totals || {});
const assetTotals = computed(() => stats.value.assets || {});

async function loadBase(): Promise<void> {
  try {
    const [statsData, providerData, templateData, employeeData] = await Promise.all([
      api.get<any>("/aigc/stats?days=7"),
      api.get<Paged<any>>("/aigc/providers?page_size=100"),
      api.get<Paged<any>>("/aigc/templates?page_size=100"),
      api.get<Paged<any>>("/digital-employees?page_size=200").catch(() => ({ items: [] })),
    ]);
    stats.value = statsData;
    providers.value = providerData.items;
    templates.value = templateData.items;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function loadTab(): Promise<void> {
  try {
    if (tab.value === "jobs") {
      jobs.value = (await api.get<Paged<any>>("/aigc/generations?page_size=100")).items;
    } else if (tab.value === "assets") {
      assets.value = (await api.get<Paged<any>>("/aigc/assets?page_size=100")).items;
    }
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function refresh(): Promise<void> {
  await loadBase();
  await loadTab();
}

async function changeTab(next: typeof tab.value): Promise<void> {
  tab.value = next;
  await loadTab();
}

function openJob(id: number): void {
  drawer.open(AigcJobDrawer, { id, onChanged: refresh });
}

function openAsset(id: number): void {
  drawer.open(AigcAssetDrawer, { id, onChanged: refresh });
}

function reviewAsset(id: number, decision: "approve" | "reject"): void {
  modal.openForm({
    title: decision === "approve" ? "通过素材" : "驳回素材",
    sub: `素材 #${id}`,
    fields: [
      { name: "score", label: "评分（0-10，可选）", type: "number", value: decision === "approve" ? 8 : 0 },
      { name: "note", label: "审核说明", type: "textarea", rows: 3 },
    ],
    submitLabel: decision === "approve" ? "确认通过" : "确认驳回",
    onSubmit: async (values) => {
      await api.post(`/aigc/assets/${id}/review`, {
        decision,
        score: Number(values.score) || 0,
        note: values.note || "",
      });
      toast.push(decision === "approve" ? "素材已通过" : "素材已驳回");
      await refresh();
    },
  });
}

async function removeAsset(id: number): Promise<void> {
  if (!confirm("确认删除该素材？")) return;
  try {
    await api.delete(`/aigc/assets/${id}`);
    toast.push("素材已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

function uploadAsset(): void {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      await api.upload("/aigc/assets/upload", file);
      toast.push("图片已上传");
      await changeTab("assets");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "上传失败", "error");
    }
  };
  input.click();
}

async function openGenerateModal(): Promise<void> {
  let imageAssets: any[] = [];
  try {
    imageAssets = (await api.get<Paged<any>>("/aigc/assets?asset_type=image&page_size=100")).items;
  } catch {
    imageAssets = [];
  }
  const enabledProviders = providers.value.filter((item) => item.enabled);
  const enabledTemplates = templates.value.filter((item) => item.enabled);
  modal.openForm({
    title: "新建 AIGC 生成任务",
    sub: "选择生成类型、服务与提示词，提交后进入生成队列。",
    wide: true,
    fields: [
      {
        name: "job_type",
        label: "生成类型",
        type: "select",
        value: "text_to_image",
        options: [
          { value: "text_to_image", label: "文生图" },
          { value: "text_to_video", label: "文生视频" },
          { value: "image_to_video", label: "图生视频" },
        ],
      },
      {
        name: "provider_id",
        label: "生成服务",
        type: "select",
        value: "",
        options: [
          { value: "", label: "自动选择默认服务" },
          ...enabledProviders.map((item) => ({
            value: item.id,
            label: `${item.name} · ${providerLabels[item.provider_type] || item.provider_type}`,
          })),
        ],
      },
      {
        name: "template_id",
        label: "提示词模板",
        type: "select",
        value: "",
        options: [
          { value: "", label: "不使用模板" },
          ...enabledTemplates.map((item) => ({
            value: item.id,
            label: `${item.name} · ${typeLabels[item.category] || item.category}`,
          })),
        ],
      },
      { name: "prompt", label: "提示词", type: "textarea", rows: 6, placeholder: "选择模板后可以留空，由模板默认变量渲染" },
      { name: "negative_prompt", label: "负向提示词", type: "textarea", rows: 2 },
      { name: "size", label: "尺寸", value: "1024x1024" },
      { name: "count", label: "数量（文生图）", type: "number", value: 1 },
      { name: "duration", label: "时长秒（视频）", type: "number", value: 5 },
      {
        name: "input_asset_id",
        label: "输入图片（图生视频）",
        type: "select",
        value: "",
        options: [
          { value: "", label: "不使用 / 不适用" },
          ...imageAssets.map((asset) => ({
            value: asset.id,
            label: `#${asset.id} ${String(asset.prompt || asset.file_name || "图片").slice(0, 28)}`,
          })),
        ],
      },
      {
        name: "employee_id",
        label: "关联数字员工（可选）",
        type: "select",
        value: "",
        options: [
          { value: "", label: "不关联" },
          ...employees.value.map((employee) => ({
            value: employee.id,
            label: `${employee.name}${employee.code ? ` · ${employee.code}` : ""}`,
          })),
        ],
      },
      { name: "template_values", label: "模板变量 JSON", type: "json", full: true, value: {} },
      { name: "priority", label: "优先级", type: "number", value: 100 },
    ],
    submitLabel: "提交生成",
    onSubmit: async (values) => {
      if (values.job_type === "image_to_video" && !values.input_asset_id) {
        throw new Error("图生视频请选择一张输入图片");
      }
      const params: Record<string, unknown> = {};
      if (values.size) params.size = values.size;
      if (values.job_type === "text_to_image") params.count = Number(values.count) || 1;
      else params.duration = Number(values.duration) || 5;
      await api.post("/aigc/generations", {
        job_type: values.job_type,
        prompt: values.prompt || "",
        negative_prompt: values.negative_prompt || "",
        provider_id: values.provider_id ? Number(values.provider_id) : null,
        template_id: values.template_id ? Number(values.template_id) : null,
        template_values: values.template_values || {},
        input_asset_id: values.input_asset_id ? Number(values.input_asset_id) : null,
        employee_id: values.employee_id ? Number(values.employee_id) : null,
        params,
        priority: Number(values.priority) || 100,
      });
      toast.push("生成任务已提交");
      await changeTab("jobs");
      await loadBase();
    },
  });
}

function createTemplate(): void {
  modal.openForm({
    title: "新建提示词模板",
    sub: "使用 {{变量名}} 占位，创建生成任务时可用默认值或自定义值渲染。",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true },
      { name: "code", label: "编码", required: true },
      {
        name: "category",
        label: "生成类型",
        type: "select",
        value: "text_to_image",
        options: [
          { value: "text_to_image", label: "文生图" },
          { value: "text_to_video", label: "文生视频" },
          { value: "image_to_video", label: "图生视频" },
        ],
      },
      { name: "body", label: "提示词正文", type: "textarea", rows: 6, required: true },
      { name: "negative_prompt", label: "负向提示词", type: "textarea", rows: 2 },
      { name: "variables", label: "变量默认值 JSON", type: "json", full: true, value: {} },
      { name: "params", label: "默认参数 JSON", type: "json", full: true, value: {} },
      {
        name: "enabled",
        label: "状态",
        type: "select",
        value: "true",
        options: [
          { value: "true", label: "启用" },
          { value: "false", label: "停用" },
        ],
      },
      { name: "description", label: "说明", full: true },
    ],
    submitLabel: "创建模板",
    onSubmit: async (values) => {
      await api.post("/aigc/templates", {
        ...values,
        enabled: values.enabled === "true",
      });
      toast.push("提示词模板已保存");
      await refresh();
    },
  });
}

function editTemplate(template: any): void {
  modal.openForm({
    title: "编辑提示词模板",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true, value: template.name },
      { name: "code", label: "编码", required: true, value: template.code },
      {
        name: "category",
        label: "生成类型",
        type: "select",
        value: template.category,
        options: [
          { value: "text_to_image", label: "文生图" },
          { value: "text_to_video", label: "文生视频" },
          { value: "image_to_video", label: "图生视频" },
        ],
      },
      { name: "body", label: "提示词正文", type: "textarea", rows: 6, required: true, value: template.body },
      { name: "negative_prompt", label: "负向提示词", type: "textarea", rows: 2, value: template.negative_prompt },
      { name: "variables", label: "变量默认值 JSON", type: "json", full: true, value: template.variables },
      { name: "params", label: "默认参数 JSON", type: "json", full: true, value: template.params },
      {
        name: "enabled",
        label: "状态",
        type: "select",
        value: String(template.enabled),
        options: [
          { value: "true", label: "启用" },
          { value: "false", label: "停用" },
        ],
      },
      { name: "description", label: "说明", full: true, value: template.description },
    ],
    submitLabel: "保存",
    onSubmit: async (values) => {
      await api.patch(`/aigc/templates/${template.id}`, {
        ...values,
        enabled: values.enabled === "true",
      });
      toast.push("提示词模板已保存");
      await refresh();
    },
  });
}

async function removeTemplate(template: any): Promise<void> {
  if (!confirm("确认删除该提示词模板？")) return;
  try {
    await api.delete(`/aigc/templates/${template.id}`);
    toast.push("模板已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

function providerFields(provider: any = null): any[] {
  const typeDefaults: Record<string, string[]> = {
    mock: ["text_to_image", "text_to_video", "image_to_video"],
    openai_image: ["text_to_image"],
    comfyui: ["text_to_image", "text_to_video", "image_to_video"],
    http_generic: ["text_to_image", "text_to_video", "image_to_video"],
  };
  return [
    { name: "name", label: "服务名称", required: true, value: provider?.name || "" },
    {
      name: "provider_type",
      label: "服务类型",
      type: "select",
      value: provider?.provider_type || "mock",
      options: [
        { value: "mock", label: "内置 Mock" },
        { value: "openai_image", label: "OpenAI 兼容图片" },
        { value: "comfyui", label: "ComfyUI" },
        { value: "http_generic", label: "通用 HTTP" },
      ],
    },
    { name: "base_url", label: "Base URL", value: provider?.base_url || "" },
    {
      name: "api_key",
      label: "API Key",
      type: "password",
      value: "",
      placeholder: provider?.has_api_key ? "已配置，留空则不修改" : "按需填写",
    },
    { name: "model", label: "模型 / 工作流名", value: provider?.model || "" },
    { name: "config", label: "扩展配置 JSON", type: "json", full: true, value: provider?.config || {} },
    {
      name: "supported_types",
      label: "支持的生成类型 JSON",
      type: "json",
      full: true,
      value: provider?.supported_types || typeDefaults[provider?.provider_type || "mock"],
    },
    { name: "cost_per_unit", label: "单价", type: "number", step: "0.01", value: provider?.cost_per_unit ?? 0 },
    {
      name: "cost_unit",
      label: "计价单位",
      type: "select",
      value: provider?.cost_unit || "image",
      options: [
        { value: "image", label: "每张图" },
        { value: "video", label: "每个视频" },
        { value: "second", label: "每秒" },
        { value: "request", label: "每次请求" },
      ],
    },
    { name: "timeout_seconds", label: "超时秒", type: "number", value: provider?.timeout_seconds || 180 },
    { name: "priority", label: "优先级", type: "number", value: provider?.priority ?? 100 },
    {
      name: "is_default",
      label: "设为默认",
      type: "select",
      value: String(provider?.is_default ?? false),
      options: [
        { value: "false", label: "否" },
        { value: "true", label: "是" },
      ],
    },
    {
      name: "enabled",
      label: "状态",
      type: "select",
      value: String(provider?.enabled ?? true),
      options: [
        { value: "true", label: "启用" },
        { value: "false", label: "停用" },
      ],
    },
    { name: "description", label: "说明", full: true, value: provider?.description || "" },
  ];
}

function saveProvider(values: Record<string, any>, provider: any = null): Promise<void> {
  const body: Record<string, any> = {
    ...values,
    base_url: values.base_url || null,
    model: values.model || null,
    cost_per_unit: Number(values.cost_per_unit) || 0,
    timeout_seconds: Number(values.timeout_seconds) || 180,
    priority: Number(values.priority) || 100,
    is_default: values.is_default === "true",
    enabled: values.enabled === "true",
  };
  if (!String(values.api_key || "").trim()) delete body.api_key;
  return provider
    ? api.patch(`/aigc/providers/${provider.id}`, body)
    : api.post("/aigc/providers", body);
}

function createProvider(): void {
  modal.openForm({
    title: "添加生成服务",
    sub: "Mock 开箱即用；ComfyUI 需要填 workflow；通用 HTTP 需配置 create / poll。",
    wide: true,
    fields: providerFields(),
    submitLabel: "添加服务",
    onSubmit: async (values) => {
      await saveProvider(values);
      toast.push("生成服务已保存");
      await refresh();
    },
  });
}

function editProvider(provider: any): void {
  modal.openForm({
    title: "编辑生成服务",
    wide: true,
    fields: providerFields(provider),
    submitLabel: "保存",
    onSubmit: async (values) => {
      await saveProvider(values, provider);
      toast.push("生成服务已保存");
      await refresh();
    },
  });
}

async function testProvider(provider: any): Promise<void> {
  try {
    const result = await api.post<any>(`/aigc/providers/${provider.id}/test`, {});
    toast.push(result.message || (result.ok ? "服务可用" : "服务不可用"), result.ok ? "success" : "error");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "测试失败", "error");
  }
}

async function removeProvider(provider: any): Promise<void> {
  if (!confirm("确认删除该生成服务？已有任务使用时会拒绝删除。")) return;
  try {
    await api.delete(`/aigc/providers/${provider.id}`);
    toast.push("生成服务已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

async function removeJob(job: any): Promise<void> {
  if (!confirm("确认删除该任务及其素材？")) return;
  try {
    await api.delete(`/aigc/generations/${job.id}`);
    toast.push("任务已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

async function cancelJob(job: any): Promise<void> {
  if (!confirm("确认取消该生成任务？")) return;
  try {
    await api.post(`/aigc/generations/${job.id}/cancel`, {});
    toast.push("任务已取消");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "取消失败", "error");
  }
}

async function retryJob(job: any): Promise<void> {
  try {
    await api.post(`/aigc/generations/${job.id}/retry`, {});
    toast.push("任务已重新入队");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "重试失败", "error");
  }
}

onMounted(async () => {
  await loadBase();
  await loadTab();
});
</script>

<template>
  <PageHeader
    eyebrow="business / aigc"
    title="AIGC 内容生成"
    sub="文生图 / 文生视频 / 图生视频：生成队列、素材库、人工审核与成本统计。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="uploadAsset"><AppIcon name="plus" />上传图片</button>
      <button class="btn btn-primary" @click="openGenerateModal"><AppIcon name="spark" />新建生成</button>
    </template>
  </PageHeader>

  <div class="aigc-stats-grid">
    <StatCard label="生成任务（7 天）" :value="totals.jobs ?? 0" :meta="`成功 ${totals.succeeded ?? 0} · 失败 ${totals.failed ?? 0}`" :index="0" />
    <StatCard label="成功率" :value="`${Math.round(Number(totals.success_rate || 0) * 100)}%`" :meta="`平均耗时 ${totals.avg_latency_ms ? fmtMs(totals.avg_latency_ms) : '—'}`" tone="var(--mint)" :index="1" />
    <StatCard label="生成成本" :value="Number(totals.cost || 0).toFixed(2)" meta="按生成服务单价估算" tone="var(--blue)" :index="2" />
    <StatCard label="待审核素材" :value="assetTotals.pending_review ?? 0" :meta="`素材 ${assetTotals.total ?? 0} · 视频 ${assetTotals.videos ?? 0}`" tone="var(--coral)" :index="3" />
  </div>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'jobs' }" @click="changeTab('jobs')">生成任务</button>
    <button class="tab" :class="{ active: tab === 'assets' }" @click="changeTab('assets')">
      素材库 <span class="dim">{{ assetTotals.total ?? 0 }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'templates' }" @click="changeTab('templates')">
      提示词模板 <span class="dim">{{ templates.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'providers' }" @click="changeTab('providers')">
      生成服务 <span class="dim">{{ providers.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'stats' }" @click="changeTab('stats')">成本统计</button>
  </div>

  <div v-if="tab === 'jobs'" class="panel">
    <DataTable
      :rows="jobs"
      :columns="[
        { label: '任务', format: (row) => `<div class='cell-main'><b>${esc(typeLabels[row.job_type] || row.job_type)} · #${row.id}</b><small class='truncate'>${esc((row.prompt || '').slice(0, 80))}</small></div>` },
        { label: '服务', format: (row) => esc(row.provider_name || '—') },
        { label: '状态', key: 'status' },
        { label: '成本', format: (row) => `<span class='mono'>${Number(row.cost || 0).toFixed(2)}</span>` },
        { label: '耗时', format: (row) => `<span class='mono dim'>${row.latency_ms ? fmtMs(row.latency_ms) : '—'}</span>` },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有生成任务"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openJob(row.id)">详情</button>
          <button v-if="['pending', 'running'].includes(row.status)" class="btn btn-sm btn-ghost" @click="cancelJob(row)">取消</button>
          <button v-if="['failed', 'cancelled'].includes(row.status)" class="btn btn-sm" @click="retryJob(row)">重试</button>
          <button v-if="!['pending', 'running'].includes(row.status)" class="btn btn-sm btn-danger" @click="removeJob(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else-if="tab === 'assets'" class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">素材库</div>
        <div class="panel-sub">生成结果与上传源图，待审核素材可人工通过或驳回。</div>
      </div>
      <span class="dim mono">{{ assets.length }} 个</span>
    </div>
    <AigcAssetGrid :assets="assets" @preview="openAsset" @review="reviewAsset" @remove="removeAsset" />
  </div>

  <div v-else-if="tab === 'templates'" class="panel">
    <div class="panel-head">
      <div><div class="panel-title">提示词模板</div><div class="panel-sub">支持变量占位与默认参数。</div></div>
      <button class="btn btn-sm" @click="createTemplate"><AppIcon name="plus" />新建模板</button>
    </div>
    <DataTable
      :rows="templates"
      :columns="[
        { label: '模板', format: (row) => `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>` },
        { label: '类型', format: (row) => `<span class='tag'>${esc(typeLabels[row.category] || row.category)}</span>` },
        { label: '变量', format: (row) => `<span class='mono dim'>${esc(Object.keys(row.variables || {}).join(', ') || '—')}</span>` },
        { label: '使用次数', format: (row) => `<span class='mono'>${row.usage_count}</span>` },
        { label: '状态', key: 'status' },
        { label: '更新', format: (row) => `<span class='muted'>${fmtDate(row.updated_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有提示词模板"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.enabled ? 'active' : 'disabled'" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-ghost" @click="editTemplate(row)">编辑</button>
          <button class="btn btn-sm btn-danger" @click="removeTemplate(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else-if="tab === 'providers'" class="panel">
    <div class="panel-head">
      <div><div class="panel-title">生成服务</div><div class="panel-sub">Mock / OpenAI / ComfyUI / 通用 HTTP。</div></div>
      <button class="btn btn-sm" @click="createProvider"><AppIcon name="plus" />添加服务</button>
    </div>
    <DataTable
      :rows="providers"
      :columns="[
        { label: '服务', format: (row) => `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(providerLabels[row.provider_type] || row.provider_type)}${row.model ? ` · ${esc(row.model)}` : ''}</small></div>` },
        { label: '地址', format: (row) => `<span class='truncate mono dim'>${esc(row.base_url || '—')}</span>` },
        { label: '支持', format: (row) => esc((row.supported_types || []).map((item: string) => typeLabels[item] || item).join(' / ') || '—') },
        { label: '单价', format: (row) => `<span class='mono'>${Number(row.cost_per_unit || 0).toFixed(2)} / ${esc(row.cost_unit)}</span>` },
        { label: '默认', key: 'default' },
        { label: '状态', key: 'status' },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有生成服务"
    >
      <template #cell-default="{ row }"><StatusPill v-if="row.is_default" status="active" /><span v-else class="dim">—</span></template>
      <template #cell-status="{ row }"><StatusPill :status="row.enabled ? 'active' : 'disabled'" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="testProvider(row)">测试</button>
          <button class="btn btn-sm btn-ghost" @click="editProvider(row)">编辑</button>
          <button class="btn btn-sm btn-danger" @click="removeProvider(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else>
    <div class="panel" style="margin-bottom: 16px">
      <div class="panel-head"><div><div class="panel-title">按生成类型</div><div class="panel-sub">最近 {{ stats.days }} 天</div></div></div>
      <DataTable
        :rows="stats.by_type || []"
        :columns="[
          { label: '类型', format: (row) => `<span class='tag'>${esc(row.label)}</span>` },
          { label: '任务', format: (row) => `<span class='mono'>${row.jobs}</span>` },
          { label: '成功 / 失败', format: (row) => `<span class='mono'>${row.succeeded} / ${row.failed}</span>` },
          { label: '成本', format: (row) => `<span class='mono'>${Number(row.cost || 0).toFixed(2)}</span>` },
        ]"
      />
    </div>
    <div class="panel" style="margin-bottom: 16px">
      <div class="panel-head"><div><div class="panel-title">按生成服务</div><div class="panel-sub">成本与成功率来源</div></div></div>
      <DataTable
        :rows="stats.by_provider || []"
        :columns="[
          { label: '服务', format: (row) => esc(row.provider) },
          { label: '任务', format: (row) => `<span class='mono'>${row.jobs}</span>` },
          { label: '成功 / 失败', format: (row) => `<span class='mono'>${row.succeeded} / ${row.failed}</span>` },
          { label: '成本', format: (row) => `<span class='mono'>${Number(row.cost || 0).toFixed(2)}</span>` },
        ]"
      />
    </div>
    <div class="panel">
      <div class="panel-head"><div><div class="panel-title">每日趋势</div><div class="panel-sub">任务量、成功失败与成本</div></div></div>
      <DataTable
        :rows="stats.daily || []"
        :columns="[
          { label: '日期', format: (row) => `<span class='mono'>${esc(row.date)}</span>` },
          { label: '任务', format: (row) => `<span class='mono'>${row.jobs}</span>` },
          { label: '成功', format: (row) => `<span class='mono'>${row.succeeded}</span>` },
          { label: '失败', format: (row) => `<span class='mono'>${row.failed}</span>` },
          { label: '成本', format: (row) => `<span class='mono'>${Number(row.cost || 0).toFixed(2)}</span>` },
        ]"
      />
    </div>
  </div>
</template>
