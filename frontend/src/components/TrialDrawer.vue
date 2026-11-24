<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ id: number; employeeName?: string }>();

const detail = ref<any>(null);
const drawer = useDrawerStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/trials/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>试运行 #{{ id }}</h3>
      <p>{{ employeeName || "—" }} · 影子试运行 / 上岗认证</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>模式</span><b class="mono">{{ detail.mode }}</b></div>
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>决策</span><b class="mono">{{ detail.decision || "—" }}</b></div>
      <div class="meta"><span>阈值</span><b class="mono">{{ detail.threshold }}</b></div>
      <div class="meta"><span>样本窗口</span><b class="mono">{{ detail.sample_size }}</b></div>
      <div class="meta"><span>时间</span><b>{{ fmtDate(detail.created_at) }}</b></div>
    </div>

    <div class="section-label">指标</div>
    <div class="metric-grid">
      <div class="metric"><span>样本</span><b>{{ detail.metrics?.samples ?? 0 }}</b></div>
      <div class="metric"><span>一次通过率</span><b>{{ detail.metrics?.one_pass_rate ?? 0 }}</b></div>
      <div class="metric"><span>接管率</span><b>{{ detail.metrics?.takeover_rate ?? 0 }}</b></div>
      <div class="metric"><span>成功率</span><b>{{ detail.metrics?.success_rate ?? 0 }}</b></div>
      <div class="metric"><span>平均尝试</span><b>{{ detail.metrics?.avg_attempts ?? 0 }}</b></div>
      <div class="metric"><span>样本充足</span><b>{{ detail.metrics?.sample_sufficient ? "是" : "否" }}</b></div>
    </div>

    <div class="section-label">样本明细</div>
    <div v-if="detail.details?.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>实例</th><th>标题</th><th>状态</th><th>尝试</th><th>接管</th><th>归因</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail.details" :key="item.instance_id">
            <td class="mono">#{{ item.instance_id }}</td>
            <td>{{ item.title }}</td>
            <td><StatusPill :status="item.status" /></td>
            <td class="mono">{{ item.attempt }}</td>
            <td class="mono">{{ item.takeover }}</td>
            <td class="mono muted">{{ (item.attributions || []).join(", ") || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">没有可用样本。</div>

    <div class="section-label">原始记录</div>
    <JsonBlock :value="detail" />
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
