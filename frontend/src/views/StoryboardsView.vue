<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import StoryboardDetailDrawer from "@/components/StoryboardDetailDrawer.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Storyboard {
  id: number;
  title: string;
  genre: string;
  style: string;
  status: string;
  scene_count: number;
  shot_count: number;
  tokens: number;
  model?: string | null;
  error?: string | null;
  created_at: string;
}

interface StoryboardDetail extends Storyboard {
  script: string;
}

const rows = ref<Storyboard[]>([]);
const loading = ref(false);
const generatingId = ref<number | null>(null);

const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await api.get<Paged<Storyboard>>("/storyboards?page_size=100");
    rows.value = data.items;
  } catch (err) {
    toast.push(errorMessage(err, "加载失败"), "error");
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  modal.openForm({
    title: "新建分镜项目",
    sub: "粘贴剧本，生成后用 DeepSeek 拆解场景与镜头。",
    wide: true,
    fields: [
      { name: "title", label: "项目名称", required: true, placeholder: "雨夜咖啡馆" },
      {
        name: "genre",
        label: "类型",
        type: "select",
        options: ["短剧", "电影", "广告", "动画"],
        value: "短剧",
      },
      { name: "style", label: "视觉风格", value: "写实电影感" },
      {
        name: "script",
        label: "剧本内容",
        type: "textarea",
        full: true,
        rows: 12,
        required: true,
        placeholder: "夜，咖啡馆。小林推门而入……",
      },
    ],
    submitLabel: "创建项目",
    onSubmit: async (values) => {
      await api.post("/storyboards", values);
      toast.push("分镜项目已创建");
      await load();
    },
  });
}

async function openEdit(row: Storyboard): Promise<void> {
  try {
    const detail = await api.get<StoryboardDetail>(`/storyboards/${row.id}`);
    modal.openForm({
      title: "编辑分镜项目",
      sub: "修改剧本、类型或风格会清空已生成分镜，需要重新生成。",
      wide: true,
      fields: [
        { name: "title", label: "项目名称", required: true, value: detail.title },
        {
          name: "genre",
          label: "类型",
          type: "select",
          options: ["短剧", "电影", "广告", "动画"],
          value: detail.genre,
        },
        { name: "style", label: "视觉风格", value: detail.style },
        {
          name: "script",
          label: "剧本内容",
          type: "textarea",
          full: true,
          rows: 12,
          required: true,
          value: detail.script,
        },
      ],
      submitLabel: "保存",
      onSubmit: async (values) => {
        await api.patch(`/storyboards/${row.id}`, values);
        toast.push("分镜项目已更新");
        await load();
      },
    });
  } catch (err) {
    toast.push(errorMessage(err, "项目详情加载失败"), "error");
  }
}

async function generate(row: Storyboard): Promise<void> {
  if (generatingId.value !== null) return;
  if (row.scene_count > 0 && !window.confirm("重新生成会覆盖现有分镜，确认继续？")) return;
  generatingId.value = row.id;
  try {
    const result = await api.post<StoryboardDetail>(`/storyboards/${row.id}/generate`, {});
    toast.push(`分镜已生成：${result.scene_count} 个场景 / ${result.shot_count} 个镜头`);
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "生成失败"), "error");
  } finally {
    generatingId.value = null;
  }
}

function openDetail(row: Storyboard): void {
  drawer.open(StoryboardDetailDrawer, { projectId: row.id });
}

async function exportStoryboard(row: Storyboard, format: "json" | "csv"): Promise<void> {
  try {
    await api.download(
      `/storyboards/${row.id}/export?format=${format}`,
      `storyboard_${row.id}.${format}`,
    );
  } catch (err) {
    toast.push(errorMessage(err, "导出失败"), "error");
  }
}

async function remove(row: Storyboard): Promise<void> {
  if (!window.confirm(`确认删除分镜项目「${row.title}」？`)) return;
  try {
    await api.delete(`/storyboards/${row.id}`);
    toast.push("分镜项目已删除");
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "删除失败"), "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="business / storyboard"
    title="AI 剧本分镜"
    sub="剧本 → 场景 → 镜头 → 画面提示词，由 DeepSeek 生成。"
  >
    <template #actions>
      <button class="btn btn-ghost" :disabled="loading" @click="load">
        <AppIcon name="refresh" />刷新
      </button>
      <button class="btn btn-primary" @click="openCreate"><AppIcon name="plus" />新建分镜</button>
    </template>
  </PageHeader>

  <div class="panel">
    <DataTable
      :rows="rows"
      :columns="[
        {
          label: '项目',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.title)}</b><small>${esc(row.genre)} · ${esc(row.style)}</small></div>`,
        },
        { label: '场景 / 镜头', format: (row) => `<span class='mono'>${row.scene_count} / ${row.shot_count}</span>` },
        { label: '状态', key: 'status' },
        { label: 'Tokens', format: (row) => `<span class='mono'>${row.tokens}</span>` },
        { label: '模型', format: (row) => `<span class='dim mono'>${esc(row.model || '—')}</span>` },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有分镜项目，先创建并生成一个。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openDetail(row)">详情</button>
          <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
          <button
            class="btn btn-sm"
            :disabled="generatingId !== null"
            @click="generate(row)"
          >
            {{ generatingId === row.id ? "生成中..." : row.scene_count ? "重新生成" : "生成分镜" }}
          </button>
          <button class="btn btn-sm btn-ghost" @click="exportStoryboard(row, 'json')">JSON</button>
          <button class="btn btn-sm btn-ghost" @click="exportStoryboard(row, 'csv')">CSV</button>
          <button class="btn btn-sm btn-danger" @click="remove(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
