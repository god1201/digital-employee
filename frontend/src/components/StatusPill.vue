<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status?: string | null; text?: string }>();

const known = new Set([
  "succeeded",
  "failed",
  "running",
  "pending",
  "waiting_human",
  "waiting",
  "cancelled",
  "active",
  "disabled",
  "allow",
  "block",
  "review",
  "open",
  "acked",
  "low",
  "medium",
  "high",
  "critical",
  "ready",
  "generating",
  "draft",
  "pending_confirmation",
  "paused",
  "approved",
  "rejected",
]);

const cls = computed(() => {
  const value = String(props.status || "");
  return known.has(value) ? `pill-${value}` : "";
});
</script>

<template>
  <span class="pill" :class="cls">{{ text || status || "unknown" }}</span>
</template>
