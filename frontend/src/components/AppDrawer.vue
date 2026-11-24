<script setup lang="ts">
import { useDrawerStore } from "@/stores/drawer";

const drawer = useDrawerStore();
</script>

<template>
  <div v-if="drawer.visible">
    <div class="drawer-backdrop" @click="drawer.close()" />
    <aside class="drawer">
      <component :is="drawer.component" v-if="drawer.component" v-bind="drawer.componentProps" />
    </aside>
  </div>
</template>
