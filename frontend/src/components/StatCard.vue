<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    meta?: string;
    tone?: string;
    index?: number;
  }>(),
  {
    meta: "",
    tone: "var(--amber)",
    index: 0,
  },
);
</script>

<template>
  <div class="stat-card" :style="{ '--tone': tone, '--i': index } as any">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value">{{ value }}</div>
    <div class="stat-meta" v-html="meta" />
  </div>
</template>
