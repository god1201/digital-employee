<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate, fmtMs } from "@/utils/format";

const props = defineProps<{
  id: number;
  employeeName?: string;
}>();

const detail = ref<any>(null);
const index = ref(0);
const playing = ref(false);
let timer: number | undefined;

const drawer = useDrawerStore();
const toast = useToastStore();

const frames = computed<any[]>(() => detail.value?.frames || []);
const current = computed<any>(() => frames.value[index.value] || null);

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/tasks/instances/${props.id}/replay`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function stop(): void {
  playing.value = false;
  if (timer) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

function play(): void {
  if (!frames.value.length) return;
  if (playing.value) {
    stop();
    return;
  }
  if (index.value >= frames.value.length - 1) index.value = 0;
  playing.value = true;
  timer = window.setInterval(() => {
    if (index.value >= frames.value.length - 1) {
      stop();
      return;
    }
    index.value += 1;
  }, 1200);
}

function step(delta: number): void {
  stop();
  index.value = Math.min(Math.max(0, index.value + delta), Math.max(0, frames.value.length - 1));
}

onMounted(load);
onBeforeUnmount(stop);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ detail?.instance?.title || `任务回放 #${id}` }}</h3>
      <p>{{ employeeName || "—" }} · {{ detail?.instance?.trace_id || "" }}</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.instance.status" /></b></div>
      <div class="meta"><span>类型</span><b class="mono">{{ detail.instance.task_type }}</b></div>
      <div class="meta"><span>尝试</span><b class="mono">{{ detail.instance.attempt }}</b></div>
      <div class="meta"><span>帧数</span><b class="mono">{{ frames.length }}</b></div>
      <div class="meta"><span>开始</span><b>{{ fmtDate(detail.instance.started_at) }}</b></div>
      <div class="meta"><span>结束</span><b>{{ fmtDate(detail.instance.finished_at) }}</b></div>
    </div>

    <div class="replay-bar">
      <button class="btn btn-sm" @click="step(-1)">上一帧</button>
      <button class="btn btn-sm btn-primary" @click="play">
        {{ playing ? "暂停" : "播放" }}
      </button>
      <button class="btn btn-sm" @click="step(1)">下一帧</button>
      <span class="mono muted">{{ frames.length ? index + 1 : 0 }} / {{ frames.length }}</span>
    </div>

    <div v-if="frames.length" class="frame-list">
      <button
        v-for="(frame, i) in frames"
        :key="frame.step_id"
        class="frame-dot"
        :class="{ active: i === index, failed: frame.status === 'failed' }"
        @click="index = i; stop()"
      >
        {{ String(i + 1).padStart(2, "0") }}
      </button>
    </div>

    <template v-if="current">
      <div class="section-label">当前帧 · {{ current.name }}</div>
      <div class="meta-grid">
        <div class="meta"><span>类型</span><b class="mono">{{ current.step_type }}</b></div>
        <div class="meta"><span>状态</span><b><StatusPill :status="current.status" /></b></div>
        <div class="meta"><span>工具</span><b class="mono">{{ current.tool_code || "—" }}</b></div>
        <div class="meta"><span>耗时</span><b class="mono">{{ fmtMs(current.latency_ms) }}</b></div>
        <div class="meta"><span>Token</span><b class="mono">{{ current.tokens }}</b></div>
        <div class="meta"><span>成本</span><b class="mono">{{ current.cost }}</b></div>
      </div>

      <div v-if="current.error" class="alert-banner" style="margin: 12px 0">
        <div><b>错误</b> · {{ current.error }}</div>
      </div>

      <div class="section-label">输入</div>
      <JsonBlock :value="current.input" />
      <div class="section-label">输出</div>
      <JsonBlock :value="current.output" />
    </template>
    <div v-else class="muted" style="font-size: 12px">该任务没有步骤帧。</div>

    <div class="section-label">接管增量</div>
    <div v-if="detail.interventions?.length" class="split">
      <span v-for="item in detail.interventions" :key="item.id" class="tag">
        #{{ item.id }} · {{ (item.diff || []).length }} 处
      </span>
    </div>
    <div v-else class="muted" style="font-size: 12px">无</div>

    <div class="section-label">失败归因</div>
    <div v-if="detail.attributions?.length" class="split">
      <span v-for="item in detail.attributions" :key="item.id" class="tag">
        {{ item.category }}
      </span>
    </div>
    <div v-else class="muted" style="font-size: 12px">无</div>
  </template>
</template>

<style scoped>
.replay-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 0;
}
.frame-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.frame-dot {
  width: 34px;
  height: 28px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
}
.frame-dot.active {
  border-color: var(--amber);
  color: var(--amber);
  background: var(--amber-soft);
}
.frame-dot.failed {
  border-color: rgba(239, 106, 91, 0.5);
  color: var(--coral);
}
</style>
