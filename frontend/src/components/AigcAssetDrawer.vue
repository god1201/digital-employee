<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtBytes, fmtDate } from "@/utils/format";

const props = defineProps<{ id: number; onChanged?: () => void }>();
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const asset = ref<any>(null);
const reviews = ref<any[]>([]);

async function load(): Promise<void> {
  try {
    [asset.value, reviews.value] = await Promise.all([
      api.get<any>(`/aigc/assets/${props.id}`),
      api.get<any[]>(`/aigc/assets/${props.id}/reviews`),
    ]);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function isVideo(): boolean {
  return String(asset.value?.mime_type || "").startsWith("video/");
}

function review(decision: "approve" | "reject"): void {
  modal.openForm({
    title: decision === "approve" ? "通过素材" : "驳回素材",
    sub: `素材 #${props.id}`,
    fields: [
      { name: "score", label: "评分（0-10，可选）", type: "number", value: decision === "approve" ? 8 : 0 },
      { name: "note", label: "审核说明", type: "textarea", rows: 3 },
    ],
    submitLabel: decision === "approve" ? "确认通过" : "确认驳回",
    onSubmit: async (values) => {
      await api.post(`/aigc/assets/${props.id}/review`, {
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

async function remove(): Promise<void> {
  if (!confirm("确认删除该素材？文件也会一并删除。")) return;
  try {
    await api.delete(`/aigc/assets/${props.id}`);
    toast.push("素材已删除");
    drawer.close();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div v-if="asset">
    <div class="drawer-head">
      <div>
        <h3>素材 #{{ asset.id }}</h3>
        <p>{{ asset.asset_type === "video" ? "视频" : "图片" }} · {{ asset.mime_type }}</p>
      </div>
      <button class="icon-btn" @click="drawer.close()"><AppIcon name="close" /></button>
    </div>

    <video v-if="isVideo()" class="aigc-media" :src="asset.public_url" controls muted playsinline />
    <img v-else class="aigc-media" :src="asset.public_url" :alt="asset.prompt" />

    <div class="meta-grid" style="margin-top: 14px">
      <div class="meta"><span>审核</span><b><StatusPill :status="asset.review_status" /></b></div>
      <div class="meta"><span>来源</span><b>{{ asset.source === "uploaded" ? "用户上传" : asset.provider_name || "生成" }}</b></div>
      <div class="meta"><span>大小</span><b>{{ fmtBytes(asset.size_bytes) }}</b></div>
      <div class="meta"><span>尺寸</span><b>{{ asset.width && asset.height ? `${asset.width}×${asset.height}` : "—" }}</b></div>
      <div class="meta"><span>时长</span><b>{{ asset.duration_seconds ? `${asset.duration_seconds}s` : "—" }}</b></div>
      <div class="meta"><span>任务</span><b>{{ asset.job_id ? `#${asset.job_id}` : "—" }}</b></div>
    </div>

    <div v-if="asset.review_note" class="alert-banner">
      <div>审核说明：{{ asset.review_note }}</div>
    </div>

    <div v-if="asset.review_status === 'pending'" style="display: flex; gap: 8px; margin: 12px 0">
      <button class="btn btn-sm" @click="review('approve')">通过</button>
      <button class="btn btn-sm btn-danger" @click="review('reject')">驳回</button>
    </div>
    <button class="btn btn-sm btn-danger" style="margin-bottom: 12px" @click="remove">删除素材</button>

    <div class="section-label">PROMPT</div>
    <pre class="code">{{ asset.prompt || "（用户上传源图）" }}</pre>

    <div class="section-label">REVIEWS</div>
    <div v-if="reviews.length" class="table-wrap">
      <table>
        <thead><tr><th>时间</th><th>结论</th><th>评分</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="item in reviews" :key="item.id">
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
            <td><StatusPill :status="item.decision === 'approve' ? 'approved' : 'rejected'" /></td>
            <td class="mono">{{ Number(item.score || 0).toFixed(1) }}</td>
            <td>{{ item.note || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">还没有审核记录</div>
  </div>
</template>
