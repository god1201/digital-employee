<script setup lang="ts">
import { computed } from "vue";

import { icons } from "./icons";

const props = defineProps<{ name: string }>();
const markup = computed(() => icons[props.name] || "");
</script>

<template>
  <span class="icon-wrap" v-html="markup" />
</template>
