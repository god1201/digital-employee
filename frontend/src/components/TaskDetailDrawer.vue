<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate, fmtMs } from "@/utils/format";

const props = defineProps<{
  id: number;
  employeeName?: string;
  onChanged?: () => void;
}>();

const detail = ref<any>(null);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/tasks/instances/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function act(action: string, body: Record<string, unknown>): Promise<void> {
  try {
    await api.post(`/tasks/instances/${props.id}/${action}`, body);
    toast.push("操作已提交");
    drawer.close();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function resume(approved: boolean): void {
  const comment = window.prompt(approved ? "批准备注（可选）" : "拒绝原因（可选）") || "";
  act("resume", { approved, comment });
}

function resumeWithCorrection(): void {
  const steps = [...(detail.value?.steps || [])].sort(
    (left: any, right: any) => left.step_index - right.step_index,
  );
  const waiting = steps.find((step: any) => step.status === "waiting");
  const draft = waiting
    ? [...steps]
        .reverse()
        .find(
          (step: any) =>
            step.status === "succeeded" &&
            (waiting.step_index === undefined || step.step_index < waiting.step_index),
        )
    : null;

  modal.openForm({
    title: "纠正后批准",
    sub: "你的终稿会与 Agent 原输出做 diff，自动写入接管增量，进入学习流水线。",
    wide: true,
    fields: [
      {
        name: "final_output",
        label: "人工终稿（JSON）",
        type: "json",
        value: draft?.output ?? {},
      },
      { name: "comment", label: "修改说明", type: "textarea", rows: 3 },
    ],
    submitLabel: "批准并记录 diff",
    onSubmit: async (values) => {
      await api.post(`/tasks/instances/${props.id}/resume`, {
        approved: true,
        comment: values.comment || null,
        final_output: values.final_output,
      });
      toast.push("已批准，接管增量已记录");
      drawer.close();
      props.onChanged?.();
    },
  });
}

function retry(): void {
  if (confirm("确认重试该失败任务？")) act("retry", {});
}

function cancel(): void {
  if (confirm("确认取消该任务？")) act("cancel", {});
}

onMounted(load);
</script>

<template>
  <div v-if="detail">
    <div class="drawer-head">
      <div>
        <h3>{{ detail.title }}</h3>
        <p>#{{ detail.id }} · {{ detail.trace_id || "" }}</p>
      </div>
      <button class="icon-btn" @click="drawer.close()">✕</button>
    </div>

    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>类型</span><b>{{ detail.task_type }}</b></div>
      <div class="meta"><span>员工</span><b>{{ employeeName || `#${detail.employee_id}` }}</b></div>
      <div class="meta"><span>尝试</span><b>{{ detail.attempt }} / {{ detail.max_attempts }}</b></div>
      <div class="meta"><span>当前步骤</span><b>{{ Number(detail.current_step_index || 0) + 1 }}</b></div>
      <div class="meta"><span>开始</span><b>{{ fmtDate(detail.started_at) }}</b></div>
      <div class="meta"><span>结束</span><b>{{ fmtDate(detail.finished_at) }}</b></div>
      <div class="meta"><span>优先级</span><b>{{ detail.priority }}</b></div>
    </div>

    <div
      v-if="['waiting_human', 'failed', 'pending', 'running'].includes(detail.status)"
      class="split"
      style="margin-bottom: 16px"
    >
      <button v-if="detail.status === 'waiting_human'" class="btn btn-primary" @click="resume(true)">
        批准继续
      </button>
      <button
        v-if="detail.status === 'waiting_human'"
        class="btn btn-ghost"
        @click="resumeWithCorrection"
      >
        纠正后批准
      </button>
      <button v-if="detail.status === 'waiting_human'" class="btn btn-danger" @click="resume(false)">
        拒绝
      </button>
      <button v-if="detail.status === 'failed'" class="btn btn-primary" @click="retry">重试</button>
      <button
        v-if="['pending', 'running', 'waiting_human'].includes(detail.status)"
        class="btn btn-ghost"
        @click="cancel"
      >
        取消
      </button>
    </div>

    <div v-if="detail.error" class="alert-banner" style="margin-bottom: 16px">
      <div><b>执行错误</b> · {{ detail.error }}</div>
    </div>

    <div class="section-label">STEP TRACE</div>
    <div v-if="detail.steps?.length" class="step-list">
      <div v-for="step in detail.steps" :key="step.id" class="step">
        <div class="idx">{{ String(step.step_index + 1).padStart(2, "0") }}</div>
        <div>
          <div class="name">{{ step.name }}</div>
          <div class="sub">
            {{ step.step_type }} · {{ step.tool_code ? `tool=${step.tool_code}` : "—" }} ·
            {{ fmtMs(step.latency_ms) }} · {{ step.tokens }} tokens
          </div>
          <div v-if="step.error" class="sub" style="color: #ffb3a9; margin-top: 6px">
            {{ step.error }}
          </div>
          <JsonBlock v-if="step.output && Object.keys(step.output).length" :value="step.output" />
        </div>
        <div class="right">
          <StatusPill :status="step.status" />
          <span class="dim mono">{{ fmtDate(step.started_at) }}</span>
        </div>
      </div>
    </div>
    <div v-else class="empty">还没有步骤记录</div>

    <div class="section-label">PLAN</div>
    <JsonBlock :value="detail.plan || []" />
    <div class="section-label">INPUT</div>
    <JsonBlock :value="detail.input || {}" />
    <div class="section-label">OUTPUT</div>
    <JsonBlock :value="detail.output || {}" />
  </div>
</template>
