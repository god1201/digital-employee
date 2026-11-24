<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ id: number; employeeName?: string }>();

const detail = ref<any>(null);
const drawer = useDrawerStore();
const toast = useToastStore();

const artifactTotal = computed(() =>
  Object.values(detail.value?.learned?.artifacts || {}).reduce<number>(
    (sum, value) => sum + Number(value),
    0,
  ),
);

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/weekly-reviews/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function deliver(): Promise<void> {
  try {
    const result = await api.post<any>(`/weekly-reviews/${props.id}/deliver`);
    const delivery = result.delivery || {};
    if (delivery.delivered) {
      toast.push("周报已投递");
    } else {
      toast.push(delivery.reason || delivery.error || "未配置投递地址", "error");
    }
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "投递失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>成长周报 #{{ id }}</h3>
      <p>{{ employeeName || "全租户" }} · {{ fmtDate(detail?.period_start) }} 起一周</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="alert-banner" style="margin-bottom: 16px">
      <div>{{ detail.summary }}</div>
    </div>

    <div class="split" style="margin-bottom: 12px; align-items: center">
      <span class="tag">状态 · {{ detail.status }}</span>
      <span v-if="detail.learned?.delivery?.at" class="tag">
        投递 · {{ detail.learned.delivery.delivered ? "成功" : "失败" }}
        · {{ fmtDate(detail.learned.delivery.at) }}
      </span>
      <button class="btn btn-sm" @click="deliver">投递到 webhook</button>
    </div>

    <div class="metric-grid">
      <div class="metric"><span>任务</span><b>{{ detail.metrics?.total_tasks ?? 0 }}</b></div>
      <div class="metric"><span>成功率</span><b>{{ detail.metrics?.success_rate ?? 0 }}</b></div>
      <div class="metric"><span>一次通过率</span><b>{{ detail.metrics?.one_pass_rate ?? 0 }}</b></div>
      <div class="metric"><span>接管率</span><b>{{ detail.metrics?.takeover_rate ?? 0 }}</b></div>
      <div class="metric"><span>学习工件</span><b>{{ artifactTotal }}</b></div>
      <div class="metric"><span>主动提问</span><b>{{ detail.metrics?.questions ?? 0 }}</b></div>
    </div>

    <div class="section-label">Top 错误</div>
    <div v-if="detail.top_errors?.length" class="table-wrap">
      <table>
        <thead><tr><th>类别</th><th>次数</th><th>建议</th></tr></thead>
        <tbody>
          <tr v-for="item in detail.top_errors" :key="item.category">
            <td>{{ item.label || item.category }}</td>
            <td class="mono">{{ item.count }}</td>
            <td class="muted">{{ item.suggestion }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">本周没有失败归因。</div>

    <div class="section-label">下周建议</div>
    <div class="split">
      <span v-for="(item, index) in detail.recommendations || []" :key="index" class="tag">
        {{ item }}
      </span>
    </div>

    <div class="section-label">学习工件</div>
    <JsonBlock :value="detail.learned" />

    <div class="section-label">全部指标</div>
    <JsonBlock :value="detail.metrics" />
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
</style>
