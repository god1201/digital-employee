<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toast";

const auth = useAuthStore();
const router = useRouter();
const toast = useToastStore();

const mode = ref<"login" | "register">("login");
const error = ref("");
const submitting = ref(false);

const form = reactive({
  tenant_name: "演示租户",
  tenant_code: "demo",
  username: "admin",
  password: "",
  full_name: "",
});

function switchMode(next: "login" | "register"): void {
  mode.value = next;
  error.value = "";
}

async function submit(): Promise<void> {
  error.value = "";
  submitting.value = true;
  try {
    if (mode.value === "register") {
      await auth.register({
        tenant_name: form.tenant_name,
        tenant_code: form.tenant_code,
        username: form.username,
        password: form.password,
        full_name: form.full_name || undefined,
      });
    }
    await auth.login({
      username: form.username,
      password: form.password,
      tenant_code: form.tenant_code || undefined,
    });
    toast.push("登录成功");
    const redirect = typeof router.currentRoute.value.query.redirect === "string"
      ? router.currentRoute.value.query.redirect
      : "/dashboard";
    await router.push(redirect);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "登录失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-wrap">
    <section class="login-brand">
      <div class="brand-mark">
        <div class="stamp">DE</div>
        <div class="name">Digital Employee<span>Control Console</span></div>
      </div>
      <div>
        <div class="signal-line" style="margin-bottom: 22px">
          system online · human in the loop
        </div>
        <h1 class="hero-type">
          <span class="solid">数字员工</span>
          <span class="outline">Operations</span>
          <span class="solid">控制台<span class="accent">.</span></span>
        </h1>
        <p class="page-sub" style="max-width: 460px; margin-top: 22px">
          授权、工具、知识与 Agent 在同一个岗位下协同。每一次执行都有轨迹，每一个动作都可追溯。
        </p>
      </div>
      <div class="brand-foot">
        <div><b>14</b>能力模块</div>
        <div><b>55+</b>API 路由</div>
        <div><b>100%</b>操作审计</div>
        <div><b>L2</b>人机协同</div>
      </div>
    </section>

    <section class="login-card">
      <div class="login-box">
        <div class="eyebrow">{{ mode === "register" ? "bootstrap" : "access control" }}</div>
        <h2>{{ mode === "register" ? "初始化管理员" : "进入控制台" }}</h2>
        <p class="hint">
          {{
            mode === "register"
              ? "仅在系统首次部署时使用，会创建租户与管理员账号。"
              : "使用管理员账号登录，查看数字员工的运行态势。"
          }}
        </p>
        <form @submit.prevent="submit">
          <div class="form-grid">
            <template v-if="mode === 'register'">
              <div class="field">
                <label>租户名称</label>
                <input v-model="form.tenant_name" name="tenant_name" required />
              </div>
              <div class="field">
                <label>租户编码</label>
                <input v-model="form.tenant_code" name="tenant_code" required />
              </div>
              <div class="field">
                <label>管理员账号</label>
                <input v-model="form.username" name="username" required />
              </div>
              <div class="field">
                <label>密码</label>
                <input v-model="form.password" name="password" type="password" minlength="8" required />
              </div>
              <div class="field full">
                <label>姓名</label>
                <input v-model="form.full_name" name="full_name" placeholder="管理员" />
              </div>
            </template>
            <template v-else>
              <div class="field">
                <label>账号</label>
                <input v-model="form.username" name="username" required />
              </div>
              <div class="field">
                <label>密码</label>
                <input v-model="form.password" name="password" type="password" required />
              </div>
              <div class="field full">
                <label>租户编码 <span class="dim">（可选）</span></label>
                <input v-model="form.tenant_code" name="tenant_code" />
              </div>
            </template>
          </div>
          <p class="form-error" :class="{ show: error }">{{ error }}</p>
          <button
            class="btn btn-primary"
            type="submit"
            style="width: 100%; margin-top: 18px; padding: 12px"
            :disabled="submitting"
          >
            {{ submitting ? "处理中..." : mode === "register" ? "创建并登录" : "登录控制台" }}
          </button>
        </form>
        <div class="login-switch">
          <span>{{ mode === "register" ? "已有账号？" : "首次部署？" }}</span>
          <button @click="switchMode(mode === 'register' ? 'login' : 'register')">
            {{ mode === "register" ? "返回登录" : "初始化管理员" }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
