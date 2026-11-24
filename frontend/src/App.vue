<script setup lang="ts">
import { RouterView } from "vue-router";

import AppDrawer from "@/components/AppDrawer.vue";
import AppModal from "@/components/AppModal.vue";
import ToastHost from "@/components/ToastHost.vue";
</script>

<template>
  <RouterView />
  <AppModal />
  <AppDrawer />
  <ToastHost />
</template>
