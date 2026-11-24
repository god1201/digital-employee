<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import LineChart from "@/components/LineChart.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatCard from "@/components/StatCard.vue";
import { useToastStore } from "@/stores/toast";
import { ago, esc, fmtDate, fmtMs, fmtNum, pct } from "@/utils/format";

interface Overview {
  totals?: Record<string, number>;
  rates?: Record<string, number>;
  performance?: Record<string, number>;
  queue?: Record<string, number>;
  workers?: Record<string, number>;
  time_series?: Array<{ date: string; total: number; succeeded: number; failed: number }>;
  recent_failures?: any[];
  by_employee?: any[];
}

const overview = ref<Overview>({});
const alerts = ref<any[]>([]);
const workers = ref<any[]>([]);
const toast = useToastStore();

const totals = computed(() => overview.value.totals || {});
const rates = computed(() => overview.value.rates || {});
const perf = computed(() => overview.value.performance || {});
const queue = computed(() => overview.value.queue || {});
const workerStats = computed(() => overview.value.workers || {});
const series = computed(() => overview.value.time_series || []);
const employeeRows = computed(() => overview.value.by_employee || []);
const failures = computed(() => overview.value.recent_failures || []);

const totalTasks = computed(() =>
  ["pending", "running", "waiting_human", "succeeded", "failed", "cancelled"].reduce(
    (sum, key) => sum + Number(totals.value[key] || 0),
    0,
  ),
);

const ring = computed(() => {
  const value = Math.max(0, Math.min(1, Number(rates.value.success_rate || 0)));
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  return {
    value,
    radius,
    circumference,
    dash: circumference * value,
    text: `${(value * 100).toFixed(1)}%`,
  };
});

async function load(): Promise<void> {
  try {
    const [overviewData, alertData, workerData] = await Promise.all([
      api.get<Overview>("/monitoring/overview?days=7"),
      api.get<any>("/alert-events?status=open&page_size=5").catch(() => null),
      api.get<any>("/monitoring/workers").catch(() => ({ workers: [] })),
    ]);
    overview.value = overviewData;
    alerts.value = alertData?.items || [];
    workers.value = workerData?.workers || [];
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="operations / overview"
    title="运行概览"
    sub="数字员工的任务吞吐、人工介入与系统健康。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <RouterLink class="btn btn-primary" to="/tasks"><AppIcon name="play" />发起任务</RouterLink>
    </template>
  </PageHeader>

  <div v-if="alerts.length" class="alert-banner">
    <div><b>{{ alerts.length }}</b> 条未确认告警需要处理</div>
    <RouterLink class="btn btn-sm btn-danger" to="/alerts">查看告警</RouterLink>
  </div>

  <section class="stat-grid">
    <StatCard
      label="任务总量"
      :value="fmtNum(totalTasks)"
      :meta="`<span>${Number(totals.succeeded || 0)} 成功</span><span class='muted'>·</span><span>${Number(totals.failed || 0)} 失败</span>`"
      tone="var(--amber)"
      :index="0"
    />
    <StatCard
      label="成功率"
      :value="pct(rates.success_rate)"
      :meta="`<span class='up'>${Number(totals.succeeded || 0)} / ${Number(totals.succeeded || 0) + Number(totals.failed || 0)} 已完成</span>`"
      tone="var(--mint)"
      :index="1"
    />
    <StatCard
      label="人工介入率"
      :value="pct(rates.human_intervention_rate)"
      :meta="`<span>${Number(totals.waiting_human || 0)} 个等待确认</span>`"
      tone="var(--blue)"
      :index="2"
    />
    <StatCard
      label="重试率"
      :value="pct(rates.retry_rate)"
      meta="<span>尝试次数 &gt; 1 的任务占比</span>"
      tone="var(--violet)"
      :index="3"
    />
    <StatCard
      label="队列积压"
      :value="fmtNum(queue.pending)"
      :meta="`<span>最老等待 ${Math.round(Number(queue.oldest_pending_age_seconds || 0))}s</span>`"
      tone="var(--coral)"
      :index="4"
    />
    <StatCard
      label="活跃 Worker"
      :value="`${Number(workerStats.active || 0)} / ${Number(workerStats.total || 0)}`"
      :meta="`<span>${Number(workerStats.stale || 0)} 个心跳超时</span>`"
      tone="var(--mint)"
      :index="5"
    />
  </section>

  <section class="grid-2">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">近 7 天任务趋势</div>
          <div class="panel-sub">总量 / 成功 / 失败</div>
        </div>
        <div class="tag">{{ fmtNum(perf.total_tokens) }} tokens</div>
      </div>
      <LineChart :series="series" />
      <div class="chart-legend">
        <span><i style="background: #e8a33d" />总量</span>
        <span><i style="background: #4fd1b0" />成功</span>
        <span><i style="background: #ef6a5b" />失败</span>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">执行质量</div>
          <div class="panel-sub">完成任务的最终状态分布</div>
        </div>
      </div>
      <div class="ring-wrap">
        <svg class="ring" width="150" height="150" viewBox="0 0 150 150">
          <circle
            cx="75"
            cy="75"
            :r="ring.radius"
            fill="none"
            stroke="rgba(151,178,204,.12)"
            stroke-width="9"
          />
          <circle
            cx="75"
            cy="75"
            :r="ring.radius"
            fill="none"
            stroke="#4fd1b0"
            stroke-width="9"
            stroke-linecap="round"
            :stroke-dasharray="`${ring.dash} ${ring.circumference}`"
            transform="rotate(-90 75 75)"
          />
          <text x="75" y="78" text-anchor="middle" class="ring-value">{{ ring.text }}</text>
          <text x="75" y="96" text-anchor="middle" class="ring-label">SUCCESS</text>
        </svg>
        <div class="ring-meta">
          <div class="row success"><span>成功</span><b>{{ Number(totals.succeeded || 0) }}</b></div>
          <div class="row fail"><span>失败</span><b>{{ Number(totals.failed || 0) }}</b></div>
          <div class="row human"><span>人工介入</span><b>{{ Number(totals.waiting_human || 0) }}</b></div>
          <div class="row"><span>平均耗时</span><b>{{ fmtMs(perf.avg_duration_ms) }}</b></div>
          <div class="row"><span>P95 耗时</span><b>{{ fmtMs(perf.p95_duration_ms) }}</b></div>
          <div class="row"><span>估算成本</span><b>{{ Number(perf.total_cost || 0).toFixed(4) }}</b></div>
        </div>
      </div>
    </div>
  </section>

  <section class="grid-2">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">员工负载</div>
          <div class="panel-sub">按数字员工聚合的任务与成功率</div>
        </div>
        <RouterLink class="panel-link" to="/employees">管理员工</RouterLink>
      </div>
      <DataTable
        :rows="employeeRows"
        :columns="[
          { label: '员工', format: (row) => `<div class='cell-main'><b>${esc(row.employee_name)}</b><small>ID ${esc(row.employee_id ?? '—')}</small></div>` },
          { label: '任务', format: (row) => esc(row.total) },
          { label: '成功 / 失败', format: (row) => `<span class='muted'>${row.succeeded} / ${row.failed}</span>` },
          { label: '成功率', format: (row) => `<span class='mono' style='color:var(--mint)'>${pct(row.success_rate)}</span>` },
          { label: '平均尝试', format: (row) => `<span class='mono'>${Number(row.avg_attempt || 0).toFixed(2)}</span>` },
        ]"
        empty-text="还没有员工任务数据"
      />
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">异常与 Worker</div>
          <div class="panel-sub">最近失败任务与消费者心跳</div>
        </div>
      </div>
      <div v-if="failures.length" class="result-list">
        <div v-for="item in failures" :key="item.id" class="result-card">
          <div class="head">
            <b>#{{ item.id }} {{ item.title }}</b>
            <span>{{ fmtDate(item.finished_at) }}</span>
          </div>
          <p style="color: #ffb3a9">{{ String(item.error || "未知错误").slice(0, 180) }}</p>
        </div>
      </div>
      <div v-else class="empty">最近没有失败任务</div>

      <div class="section-label">WORKERS</div>
      <div v-if="workers.length">
        <div v-for="worker in workers" :key="worker.worker_id" class="result-card" style="margin-bottom: 8px">
          <div class="head">
            <b>{{ worker.worker_id }}</b>
            <span>{{ worker.active ? "active" : "disabled" }}</span>
          </div>
          <p class="muted">
            {{ worker.hostname }} · PID {{ worker.pid }} · 当前任务 {{ worker.current_tasks }} ·
            {{ ago(worker.last_seen_at) }}
          </p>
        </div>
      </div>
      <div v-else class="empty">没有 Worker 心跳</div>
    </div>
  </section>
</template>
