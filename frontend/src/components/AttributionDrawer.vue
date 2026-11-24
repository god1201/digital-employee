<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{
  id: number;
  employeeName?: string;
  onChanged?: () => void;
}>();

const detail = ref<any>(null);
const drawer = useDrawerStore();
const toast = useToastStore();

const isPermission = computed(() => detail.value?.category === "permission_violation");

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/attributions/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function createArtifact(): Promise<void> {
  try {
    await api.post(`/attributions/${props.id}/artifact`, {});
    toast.push("学习工件已进入审批队列");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

async function resolve(): Promise<void> {
  try {
    await api.patch(`/attributions/${props.id}`, { status: "resolved" });
    toast.push("归因已解决");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

async function reanalyzeLlm(): Promise<void> {
  try {
    detail.value = await api.post(`/attributions/${props.id}/reanalyze-llm`, {});
    toast.push("LLM 复核完成");
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "LLM 复核失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>失败归因 #{{ id }}</h3>
      <p>{{ employeeName || "—" }} · 归因 → 路由 → 修复</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>类别</span><b>{{ detail.category_label }}</b></div>
      <div class="meta"><span>置信度</span><b class="mono">{{ detail.confidence }}</b></div>
      <div class="meta"><span>来源</span><b class="mono">{{ detail.source }}</b></div>
      <div class="meta"><span>路由动作</span><b class="mono">{{ detail.routed_action }}</b></div>
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>任务实例</span><b class="mono">#{{ detail.instance_id ?? "—" }}</b></div>
      <div class="meta"><span>接管增量</span><b class="mono">#{{ detail.intervention_id ?? "—" }}</b></div>
      <div class="meta"><span>Trace</span><b class="mono">{{ detail.trace_id || "—" }}</b></div>
      <div class="meta"><span>时间</span><b>{{ fmtDate(detail.created_at) }}</b></div>
    </div>

    <div v-if="isPermission" class="alert-banner" style="margin-bottom: 16px">
      <div><b>越权/合规类失败</b> · 禁止进入学习，请收紧权限并告警。</div>
    </div>

    <div class="section-label">修复建议</div>
    <p class="muted" style="font-size: 12.5px; line-height: 1.8">{{ detail.suggestion }}</p>

    <div class="section-label">判定信号</div>
    <div v-if="detail.signals?.length" class="split">
      <span v-for="(signal, index) in detail.signals" :key="index" class="tag">{{ signal }}</span>
    </div>
    <div v-else class="muted" style="font-size: 12px">无</div>

    <div class="section-label">原始记录</div>
    <JsonBlock :value="detail" />

    <div class="split" style="margin-top: 18px">
      <button
        v-if="!isPermission && detail.status !== 'resolved'"
        class="btn btn-primary"
        @click="createArtifact"
      >
        转为学习工件
      </button>
      <button
        v-if="!isPermission && !detail.artifact_id && detail.status !== 'resolved'"
        class="btn btn-ghost"
        @click="reanalyzeLlm"
      >
        LLM 复核
      </button>
      <button v-if="detail.status !== 'resolved'" class="btn btn-ghost" @click="resolve">
        标记已解决
      </button>
      <button class="btn btn-ghost" @click="drawer.close()">关闭</button>
    </div>
  </template>
</template>
