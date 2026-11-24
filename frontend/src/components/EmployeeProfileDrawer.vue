<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import LineChart from "@/components/LineChart.vue";
import RadarChart from "@/components/RadarChart.vue";
import RateCurve from "@/components/RateCurve.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

const props = defineProps<{ employee: Employee }>();

const profile = ref<any>(null);
const memory = ref<any>(null);
const outcomes = ref<any>(null);
const trend = ref<any>(null);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

const categoryLabels: Record<string, string> = {
  knowledge_missing: "知识缺失",
  retrieval_miss: "检索未召回",
  tool_misuse: "工具用错",
  planning_error: "规划错误",
  style_mismatch: "风格不符",
  permission_violation: "越权/合规",
  intent_misunderstanding: "理解偏差",
  unknown: "未知",
};

async function load(): Promise<void> {
  try {
    const [profileData, memoryData, outcomeData, trendData] = await Promise.all([
      api.get<any>(`/digital-employees/${props.employee.id}/profile`),
      api.get<any>(`/digital-employees/${props.employee.id}/memories`),
      api.get<any>(`/outcome-events/stats?employee_id=${props.employee.id}`),
      api
        .get<any>(`/digital-employees/${props.employee.id}/profile/trend?days=30`)
        .catch(() => null),
    ]);
    profile.value = profileData;
    memory.value = memoryData;
    outcomes.value = outcomeData.outcomes || {};
    trend.value = trendData;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function compressMemory(): void {
  modal.openForm({
    title: "压缩情景记忆",
    sub: "把历史任务压缩为一条程序记忆候选，仍需审批后生效。",
    fields: [
      { name: "before_days", label: "压缩多少天前的任务", type: "number", value: 30 },
      { name: "limit", label: "最多压缩任务数", type: "number", value: 100 },
    ],
    submitLabel: "生成压缩工件",
    onSubmit: async (values) => {
      await api.post(
        `/digital-employees/${props.employee.id}/memories/compress`,
        {
          before_days: Number(values.before_days),
          limit: Number(values.limit),
        },
      );
      toast.push("压缩工件已进入审批队列");
      await load();
    },
  });
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee.name }} · 数字履历</h3>
      <p>{{ employee.code }} · 成长档案与上岗状态</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!profile" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="metric-grid">
      <div class="metric"><span>任务总数</span><b>{{ profile.total_tasks }}</b></div>
      <div class="metric"><span>一次通过率</span><b>{{ profile.one_pass_rate }}</b></div>
      <div class="metric"><span>接管率</span><b>{{ profile.takeover_rate }}</b></div>
    </div>

    <div class="section-label">能力雷达</div>
    <RadarChart v-if="profile.capability_radar?.length" :axes="profile.capability_radar" />
    <div v-else class="muted" style="font-size: 12px">暂无足够数据绘制雷达图。</div>

    <div class="section-label">学习曲线（近 30 天）</div>
    <div v-if="trend?.series?.length" class="trend-block">
      <RateCurve :series="trend.series" />
      <div class="trend-volume">
        <LineChart :series="trend.series" />
      </div>
    </div>
    <div v-else class="muted" style="font-size: 12px">暂无近期任务数据。</div>

    <div class="section-label">任务状态</div>
    <div class="split">
      <span v-for="(count, status) in profile.task_counts" :key="status" class="tag">
        {{ status }} · {{ count }}
      </span>
      <span v-if="!Object.keys(profile.task_counts).length" class="muted">暂无任务</span>
    </div>

    <div class="section-label">学习工件</div>
    <div class="split">
      <span v-for="(count, status) in profile.artifact_counts" :key="status" class="tag">
        {{ status }} · {{ count }}
      </span>
      <span v-if="!Object.keys(profile.artifact_counts).length" class="muted">暂无工件</span>
    </div>

    <div class="section-label">失败归因分布</div>
    <div class="split">
      <span v-for="(count, category) in profile.attribution_counts" :key="category" class="tag">
        {{ categoryLabels[category] || category }} · {{ count }}
      </span>
      <span v-if="!Object.keys(profile.attribution_counts).length" class="muted">暂无归因</span>
    </div>

    <div class="section-label">知识覆盖</div>
    <div class="split">
      <span class="tag">知识库 · {{ profile.knowledge_coverage?.knowledge_bases ?? 0 }}</span>
      <span class="tag">分块 · {{ profile.knowledge_coverage?.chunks ?? 0 }}</span>
    </div>

    <div class="section-label">分层记忆</div>
    <div class="split">
      <span class="tag">工作记忆 · {{ memory?.layers?.working?.recent_tasks ?? 0 }}</span>
      <span class="tag">语义 · {{ (memory?.layers?.semantic?.artifacts || []).length }}</span>
      <span class="tag">程序 · {{ (memory?.layers?.procedural?.artifacts || []).length }}</span>
      <span class="tag">人格 · {{ (memory?.layers?.persona?.artifacts || []).length }}</span>
      <span class="tag">偏好 · {{ memory?.layers?.preference?.active_count ?? 0 }}</span>
      <span class="tag">示范案例 · {{ profile.few_shot_count ?? 0 }}</span>
    </div>
    <div class="split" style="margin-top: 8px">
      <button class="btn btn-sm btn-ghost" @click="compressMemory">压缩情景记忆</button>
    </div>

    <div class="section-label">同类错误复发</div>
    <div class="split">
      <span v-for="(count, category) in profile.recurrence || {}" :key="category" class="tag">
        {{ categoryLabels[category] || category }} · {{ count }}
      </span>
      <span v-if="!Object.keys(profile.recurrence || {}).length" class="muted">暂无复发</span>
    </div>

    <div class="section-label">隐式学习信号</div>
    <div class="split">
      <span v-for="(count, type) in profile.implicit_signals || {}" :key="type" class="tag">
        {{ type }} · {{ count }}
      </span>
      <span v-if="!Object.keys(profile.implicit_signals || {}).length" class="muted">
        暂无
      </span>
    </div>

    <div class="section-label">业务结果回执</div>
    <div v-if="Object.keys(outcomes || {}).length" class="table-wrap">
      <table>
        <thead><tr><th>类型</th><th>总数</th><th>成功</th><th>成功率</th></tr></thead>
        <tbody>
          <tr v-for="(item, type) in outcomes" :key="type">
            <td class="mono">{{ type }}</td>
            <td>{{ item.total }}</td>
            <td>{{ item.success }}</td>
            <td>{{ item.success_rate }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">暂无业务回执。</div>

    <div class="section-label">上岗认证</div>
    <div v-if="profile.certification" class="alert-banner">
      <div>
        <b>{{ profile.certification.level === "certified" ? "已认证" : "未通过" }}</b>
        · 得分 {{ profile.certification.score }} / 阈值 {{ profile.certification.threshold }}
        · 决策 {{ profile.certification.decision }}
        · {{ fmtDate(profile.certification.decided_at) }}
      </div>
    </div>
    <div v-else class="muted" style="font-size: 12px">尚未做上岗认证。</div>

    <div class="section-label">最近试运行</div>
    <div v-if="profile.trials?.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>模式</th><th>状态</th><th>得分</th><th>阈值</th><th>决策</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in profile.trials" :key="item.id">
            <td class="mono">#{{ item.id }}</td>
            <td class="mono">{{ item.mode }}</td>
            <td><StatusPill :status="item.status" /></td>
            <td><b>{{ item.score }}</b></td>
            <td class="mono">{{ item.threshold }}</td>
            <td class="mono">{{ item.decision || "—" }}</td>
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">暂无试运行记录。</div>
  </template>
</template>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.metric {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric span {
  font-size: 10.5px;
  color: var(--dim);
}
.metric b {
  font-family: var(--mono);
  font-size: 14px;
}
.trend-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.trend-volume {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 8px 10px 2px;
}
.trend-volume :deep(svg) {
  width: 100%;
  height: auto;
  display: block;
}
</style>
