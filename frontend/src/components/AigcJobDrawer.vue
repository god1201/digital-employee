<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AigcAssetDrawer from "@/components/AigcAssetDrawer.vue";
import AigcAssetGrid from "@/components/AigcAssetGrid.vue";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate, fmtMs } from "@/utils/format";

const props = defineProps<{ id: number; onChanged?: () => void }>();
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const job = ref<any>(null);

async function load(): Promise<void> {
  try {
    job.value = await api.get(`/aigc/generations/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function openAsset(id: number): void {
  drawer.open(AigcAssetDrawer, { id, onChanged: load });
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
      await load();
      props.onChanged?.();
    },
  });
}

async function removeAsset(id: number): Promise<void> {
  if (!confirm("确认删除该素材？")) return;
  try {
    await api.delete(`/aigc/assets/${id}`);
    toast.push("素材已删除");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

async function act(action: "cancel" | "retry" | "delete"): Promise<void> {
  const labels = { cancel: "取消", retry: "重试", delete: "删除" };
  if (!confirm(`确认${labels[action]}该生成任务？`)) return;
  try {
    if (action === "delete") {
      await api.delete(`/aigc/generations/${props.id}`);
      toast.push("任务已删除");
      drawer.close();
    } else {
      await api.post(`/aigc/generations/${props.id}/${action}`, {});
      toast.push(action === "cancel" ? "任务已取消" : "任务已重新入队");
      await load();
    }
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div v-if="job">
    <div class="drawer-head">
      <div>
        <h3>生成任务 #{{ job.id }}</h3>
        <p>{{ job.job_type }} · {{ job.provider_name || "—" }}</p>
      </div>
      <button class="icon-btn" @click="drawer.close()"><AppIcon name="close" /></button>
    </div>

    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="job.status" /></b></div>
      <div class="meta"><span>模板</span><b>{{ job.template_name || "—" }}</b></div>
      <div class="meta"><span>成本</span><b>{{ Number(job.cost || 0).toFixed(2) }} / 预估 {{ Number(job.estimated_cost || 0).toFixed(2) }}</b></div>
      <div class="meta"><span>耗时</span><b>{{ job.latency_ms ? fmtMs(job.latency_ms) : "—" }}</b></div>
      <div class="meta"><span>尝试</span><b>{{ job.attempt }} / {{ job.max_attempts }}</b></div>
      <div class="meta"><span>创建</span><b>{{ fmtDate(job.created_at) }}</b></div>
    </div>

    <div v-if="job.error" class="alert-banner"><div>{{ job.error }}</div></div>

    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0">
      <button v-if="['pending', 'running'].includes(job.status)" class="btn btn-sm btn-ghost" @click="act('cancel')">取消</button>
      <button v-if="['failed', 'cancelled'].includes(job.status)" class="btn btn-sm" @click="act('retry')">重试</button>
      <button v-if="!['pending', 'running'].includes(job.status)" class="btn btn-sm btn-danger" @click="act('delete')">删除</button>
    </div>

    <div class="section-label">PROMPT</div>
    <pre class="code">{{ job.prompt || "" }}</pre>
    <div class="section-label">PARAMS</div>
    <JsonBlock :value="job.params || {}" />
    <div class="section-label">RISK</div>
    <JsonBlock :value="job.risk || {}" />
    <div class="section-label">ASSETS</div>
    <AigcAssetGrid
      :assets="job.assets || []"
      @preview="openAsset"
      @review="reviewAsset"
      @remove="removeAsset"
    />
  </div>
</template>
