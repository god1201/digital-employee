<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";

interface RolePreset {
  id: number;
  code: string;
  name: string;
  description?: string;
  default_skills?: string[];
  tool_groups?: string[];
  approval_threshold: string;
  sandbox: string;
  status: string;
  is_builtin: boolean;
}

defineProps<{ preset: RolePreset }>();

const drawer = useDrawerStore();
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ preset.name }}</h3>
      <p>{{ preset.code }} · {{ preset.is_builtin ? "平台内置" : "自定义角色" }}</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="meta-grid">
    <div class="meta">
      <span>审批阈值</span>
      <b>{{ preset.approval_threshold }}</b>
    </div>
    <div class="meta">
      <span>沙盒</span>
      <b>{{ preset.sandbox }}</b>
    </div>
    <div class="meta">
      <span>状态</span>
      <b><StatusPill :status="preset.status" /></b>
    </div>
    <div class="meta">
      <span>来源</span>
      <b>{{ preset.is_builtin ? "BUILT-IN" : "CUSTOM" }}</b>
    </div>
  </div>

  <div class="section-label">默认 Skills</div>
  <div class="split">
    <span v-for="skill in preset.default_skills || []" :key="skill" class="tag">{{ skill }}</span>
    <span v-if="!(preset.default_skills || []).length" class="muted">未配置</span>
  </div>

  <div class="section-label">工具组</div>
  <div class="split">
    <span v-for="tool in preset.tool_groups || []" :key="tool" class="tag">{{ tool }}</span>
    <span v-if="!(preset.tool_groups || []).length" class="muted">未配置</span>
  </div>

  <div class="section-label">说明</div>
  <p class="muted" style="font-size: 12px; line-height: 1.7">{{ preset.description || "无" }}</p>
</template>
