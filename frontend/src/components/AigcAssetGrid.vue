<script setup lang="ts">
import StatusPill from "@/components/StatusPill.vue";
import { esc, fmtBytes } from "@/utils/format";

defineProps<{ assets: any[] }>();
defineEmits<{
  (event: "preview", id: number): void;
  (event: "review", id: number, decision: "approve" | "reject"): void;
  (event: "remove", id: number): void;
}>();

function isVideo(asset: any): boolean {
  return String(asset.mime_type || "").startsWith("video/");
}
</script>

<template>
  <div v-if="!assets.length" class="empty">还没有素材。</div>
  <div v-else class="asset-grid">
    <div v-for="asset in assets" :key="asset.id" class="asset-card">
      <div class="asset-thumb">
        <video
          v-if="isVideo(asset)"
          :src="asset.public_url"
          controls
          muted
          playsinline
          preload="metadata"
        />
        <img v-else :src="asset.public_url" :alt="asset.prompt || 'AIGC 素材'" loading="lazy" />
      </div>
      <div class="asset-body">
        <div class="cell-main">
          <b>#{{ asset.id }} · {{ asset.asset_type === "video" ? "视频" : "图片" }}</b>
          <small>{{ asset.provider_name || (asset.source === "uploaded" ? "用户上传" : "—") }}</small>
        </div>
        <div class="asset-prompt">{{ asset.prompt || "（用户上传源图）" }}</div>
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px">
          <StatusPill :status="asset.review_status" />
          <span class="dim mono" style="font-size: 10px">{{ fmtBytes(asset.size_bytes) }}</span>
        </div>
        <div class="asset-actions">
          <button class="btn btn-sm" @click="$emit('preview', asset.id)">预览</button>
          <template v-if="asset.review_status === 'pending'">
            <button class="btn btn-sm" @click="$emit('review', asset.id, 'approve')">通过</button>
            <button class="btn btn-sm btn-danger" @click="$emit('review', asset.id, 'reject')">驳回</button>
          </template>
          <button class="btn btn-sm btn-ghost" @click="$emit('remove', asset.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>
