<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { navSections } from "@/config/nav";
import { useAuthStore } from "@/stores/auth";
import AppIcon from "./AppIcon.vue";
import EmployeeDock from "./EmployeeDock.vue";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const clock = ref("--:--:--");
const envLabel = import.meta.env.DEV ? "DEV" : "PROD";
let timer: number | undefined;

const initials = computed(() =>
  String(auth.user?.full_name || auth.user?.username || "A").slice(0, 1).toUpperCase(),
);

function tick(): void {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  clock.value = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function refresh(): void {
  window.location.reload();
}

function logout(): void {
  auth.logout();
}

function isActive(key: string): boolean {
  return route.path === `/${key}` || route.path.startsWith(`/${key}/`);
}

onMounted(async () => {
  tick();
  timer = window.setInterval(tick, 1000);
  if (auth.token && !auth.user) {
    try {
      await auth.fetchMe();
    } catch {
      auth.logout();
    }
  }
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand">
        <div class="stamp">DE</div>
        <div class="name">数字员工<small>CONTROL</small></div>
      </div>
      <nav class="nav">
        <div v-for="section in navSections" :key="section.section" class="nav-section">
          <div class="nav-label">{{ section.section }}</div>
          <RouterLink
            v-for="item in section.items"
            :key="item.key"
            class="nav-item"
            :class="{ active: isActive(item.key) }"
            :to="`/${item.key}`"
          >
            <AppIcon :name="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>
      <EmployeeDock />
      <div class="rail-foot">
        <div>v0.1.0 · <span class="env">{{ envLabel }}</span></div>
        <div>tenant / {{ auth.user?.tenant_id ?? "—" }}</div>
      </div>
    </aside>
    <div class="work">
      <header class="topbar">
        <div class="status">
          <span class="dot" />
          <span>系统在线</span>
          <span class="clock">{{ clock }}</span>
        </div>
        <div class="top-actions">
          <button class="btn btn-icon" title="刷新" @click="refresh">
            <AppIcon name="refresh" />
          </button>
          <div class="user-chip">
            <span class="avatar">{{ initials }}</span>
            <span>{{ auth.user?.username || "admin" }}</span>
          </div>
          <button class="btn btn-icon" title="退出" @click="logout">
            <AppIcon name="logout" />
          </button>
        </div>
      </header>
      <main id="view" class="view">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
/* 让员工坞固定在左下角：只让导航滚动，品牌/坞/页脚常驻 */
.rail {
  overflow: hidden;
}
.nav {
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}
</style>
