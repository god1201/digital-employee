<script setup lang="ts">
defineProps<{
  eyebrow: string;
  title: string;
  sub: string;
}>();
</script>

<template>
  <div class="page-head">
    <div>
      <div class="eyebrow">{{ eyebrow }}</div>
      <h1 class="page-title">{{ title }}</h1>
      <p class="page-sub">{{ sub }}</p>
    </div>
    <div class="page-actions">
      <slot name="actions" />
    </div>
  </div>
</template>
