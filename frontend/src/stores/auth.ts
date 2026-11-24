import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/api/client";
import type { LoginResponse, User } from "@/api/types";

function readUser(): User | null {
  try {
    const raw = localStorage.getItem("de.user");
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem("de.token") || "");
  const user = ref<User | null>(readUser());
  const isAuthenticated = computed(() => Boolean(token.value));
  const displayName = computed(() => user.value?.full_name || user.value?.username || "admin");

  function persist(): void {
    if (token.value) localStorage.setItem("de.token", token.value);
    else localStorage.removeItem("de.token");
    if (user.value) localStorage.setItem("de.user", JSON.stringify(user.value));
    else localStorage.removeItem("de.user");
  }

  async function login(payload: {
    username: string;
    password: string;
    tenant_code?: string;
  }): Promise<LoginResponse> {
    const data = await api.post<LoginResponse>("/auth/login", payload);
    token.value = data.access_token;
    user.value = data.user;
    persist();
    return data;
  }

  async function register(payload: Record<string, unknown>): Promise<User> {
    return api.post<User>("/auth/register", payload);
  }

  async function fetchMe(): Promise<User> {
    const data = await api.get<User>("/auth/me");
    user.value = data;
    persist();
    return data;
  }

  function logout(): void {
    token.value = "";
    user.value = null;
    persist();
    window.location.hash = "#/login";
  }

  return {
    token,
    user,
    isAuthenticated,
    displayName,
    login,
    register,
    fetchMe,
    logout,
  };
});
