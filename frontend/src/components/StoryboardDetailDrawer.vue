<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Shot {
  id: number;
  shot_index: number;
  shot_type: string;
  camera_movement: string;
  duration_seconds: number;
  dialogue: string;
  description: string;
  image_prompt: string;
  audio_note: string;
}

interface Scene {
  id: number;
  scene_index: number;
  location: string;
  time_of_day: string;
  characters: string[];
  summary: string;
  mood: string;
  shots: Shot[];
}

interface StoryboardDetail {
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
  script: string;
  scenes: Scene[];
}

const props = defineProps<{ projectId: number }>();

const drawer = useDrawerStore();
const toast = useToastStore();
const detail = ref<StoryboardDetail | null>(null);
const loading = ref(true);
const error = ref("");

const shotColumns = [
  { label: "镜头", format: (row: Shot) => `<span class='mono'>${esc(row.shot_index)}</span>` },
  { label: "景别", format: (row: Shot) => `<span class='tag'>${esc(row.shot_type)}</span>` },
  { label: "运镜", format: (row: Shot) => esc(row.camera_movement) },
  { label: "时长", format: (row: Shot) => `<span class='mono'>${esc(row.duration_seconds)}s</span>` },
  {
    label: "台词 / 画面",
    format: (row: Shot) =>
      `<div class='cell-main'><b>${esc(row.dialogue || "—")}</b><small>${esc(row.description || "")}</small></div>`,
  },
  {
    label: "画面提示词",
    format: (row: Shot) =>
      `<span class='truncate mono dim' title='${esc(row.image_prompt)}'>${esc(row.image_prompt)}</span>`,
  },
];

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await api.get<StoryboardDetail>(`/storyboards/${props.projectId}`);
  } catch (err) {
    error.value = errorMessage(err, "分镜详情加载失败");
    toast.push(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function exportStoryboard(format: "json" | "csv"): Promise<void> {
  try {
    await api.download(
      `/storyboards/${props.projectId}/export?format=${format}`,
      `storyboard_${props.projectId}.${format}`,
    );
  } catch (err) {
    toast.push(errorMessage(err, "导出失败"), "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ detail?.title || "分镜详情" }}</h3>
      <p v-if="detail">{{ detail.genre }} · {{ detail.style }}</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="loading" class="skeleton" style="height: 200px" />
  <EmptyState v-else-if="error" :text="error" />
  <template v-else-if="detail">
    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>场景 / 镜头</span><b>{{ detail.scene_count }} / {{ detail.shot_count }}</b></div>
      <div class="meta"><span>Tokens</span><b>{{ detail.tokens }}</b></div>
      <div class="meta"><span>模型</span><b>{{ detail.model || "—" }}</b></div>
      <div class="meta"><span>创建</span><b>{{ fmtDate(detail.created_at) }}</b></div>
      <div class="meta">
        <span>导出</span>
        <b>
          <span class="panel-link" @click="exportStoryboard('json')">JSON</span>
          ·
          <span class="panel-link" @click="exportStoryboard('csv')">CSV</span>
        </b>
      </div>
    </div>

    <div v-if="detail.error" class="alert-banner">
      <div>{{ detail.error }}</div>
    </div>

    <div class="section-label">SCRIPT</div>
    <pre class="code">{{ detail.script || "" }}</pre>

    <div class="section-label">SCENES &amp; SHOTS</div>
    <template v-if="detail.scenes.length">
      <div v-for="scene in detail.scenes" :key="scene.id" class="panel" style="margin-top: 14px">
        <div class="panel-head">
          <div>
            <div class="panel-title">
              场景 {{ scene.scene_index }} · {{ scene.location || "未设置地点" }}
            </div>
            <div class="panel-sub">
              {{ scene.time_of_day || "—" }} ·
              {{ (scene.characters || []).join("、") || "无角色" }} ·
              {{ scene.mood || "" }}
            </div>
          </div>
        </div>
        <p class="muted" style="font-size: 12px; line-height: 1.7">{{ scene.summary || "" }}</p>
        <DataTable
          :rows="scene.shots"
          :columns="shotColumns"
          empty-text="没有镜头"
        />
      </div>
    </template>
    <EmptyState v-else text="还没有生成分镜，点击生成按钮。" />
  </template>
</template>
