<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";

interface Employee {
  id: number;
  name: string;
  code: string;
}

const props = defineProps<{ employee: Employee; onChanged?: () => void }>();

const skills = ref<any[]>([]);
const context = ref<any>(null);
const packages = ref<any[]>([]);
const employees = ref<Employee[]>([]);
const recommendNeed = ref("");
const recommendMode = ref("rule");
const recommendations = ref<any[]>([]);

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [skillData, contextData, packageData, employeeData] = await Promise.all([
      api.get<any[]>(`/digital-employees/${props.employee.id}/skills`),
      api.get<any>(`/digital-employees/${props.employee.id}/skills/context`),
      api.get<any>("/skill-packages?page_size=200"),
      api.get<any>("/digital-employees?page_size=200"),
    ]);
    skills.value = skillData;
    context.value = contextData;
    packages.value = packageData.items;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function install(): void {
  const available = packages.value.filter(
    (item) => item.status === "published" && !skills.value.some((s) => s.skill_code === item.code),
  );
  if (!available.length) {
    toast.push("没有可安装的技能", "info");
    return;
  }
  modal.openForm({
    title: "装配技能",
    sub: "安装时会自动解析依赖并检查冲突，权限并集变化会提示。",
    fields: [
      {
        name: "code",
        label: "技能",
        type: "select",
        required: true,
        options: available.map((item) => ({
          value: item.code,
          label: `${item.name} · v${item.version} · ${item.category}`,
        })),
      },
    ],
    submitLabel: "安装",
    onSubmit: async (values) => {
      const result = await api.post<any>(
        `/digital-employees/${props.employee.id}/skills`,
        { code: values.code },
      );
      toast.push(`已安装 ${result.installed.length} 个技能（含依赖）`);
      for (const warning of result.warnings || []) toast.push(warning, "info");
      await load();
      props.onChanged?.();
    },
  });
}

async function upgrade(skill: any): Promise<void> {
  if (!confirm(`确认升级 ${skill.skill_code} 到最新版本？有评估套件时会自动回归。`)) return;
  try {
    const result = await api.post<any>(
      `/digital-employees/${props.employee.id}/skills/${skill.skill_code}/upgrade`,
      {},
    );
    toast.push(`已升级到 v${result.skill.version}`);
    for (const warning of result.warnings || []) toast.push(warning, "info");
    for (const run of result.runs || []) {
      toast.push(`评估 suite#${run.suite_id}: ${run.before} → ${run.after}`, "info");
    }
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "升级失败", "error");
  }
}

async function toggle(skill: any): Promise<void> {
  try {
    await api.post(
      `/digital-employees/${props.employee.id}/skills/${skill.skill_code}/toggle`,
      { enabled: skill.status !== "active" },
    );
    toast.push(skill.status === "active" ? "技能已停用" : "技能已启用");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function copyFrom(): void {
  modal.openForm({
    title: "从其他员工复制技能",
    sub: "把他人已经验证好用的技能装配到本员工，依赖会一并解析。",
    fields: [
      {
        name: "source_employee_id",
        label: "源员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value
          .filter((item) => item.id !== props.employee.id)
          .map((item) => ({ value: item.id, label: `${item.name} · ${item.code}` })),
      },
      { name: "skill_code", label: "技能编码", required: true, placeholder: "data.report" },
    ],
    submitLabel: "复制安装",
    onSubmit: async (values) => {
      const result = await api.post<any>(
        `/digital-employees/${props.employee.id}/skills/copy`,
        values,
      );
      toast.push(`已复制 ${result.installed.length} 个技能（含依赖）`);
      for (const warning of result.warnings || []) toast.push(warning, "info");
      await load();
      props.onChanged?.();
    },
  });
}

async function recommend(): Promise<void> {
  if (!recommendNeed.value.trim()) {
    toast.push("先描述希望员工胜任的能力", "info");
    return;
  }
  try {
    const useLlm = recommendMode.value === "llm" ? "true" : "false";
    recommendations.value = await api.get<any[]>(
      `/digital-employees/${props.employee.id}/skills/recommend?need=${encodeURIComponent(
        recommendNeed.value.trim(),
      )}&use_llm=${useLlm}`,
    );
    if (!recommendations.value.length) toast.push("没有匹配的技能", "info");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "推荐失败", "error");
  }
}

async function installCode(code: string): Promise<void> {
  try {
    const result = await api.post<any>(
      `/digital-employees/${props.employee.id}/skills`,
      { code, source: "ai_suggest" },
    );
    toast.push(`已安装 ${result.installed.length} 个技能（含依赖）`);
    for (const warning of result.warnings || []) toast.push(warning, "info");
    recommendations.value = recommendations.value.filter((item) => item.code !== code);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "安装失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee.name }} · 技能装配</h3>
      <p>{{ employee.code }} · 依赖 / 冲突 / 权限并集</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="meta-grid">
    <div class="meta"><span>技能数</span><b>{{ context?.count ?? skills.length }}</b></div>
    <div class="meta"><span>只读</span><b>{{ context?.permissions?.read_only ? "是" : "否" }}</b></div>
    <div class="meta"><span>风险</span><b><StatusPill :status="context?.permissions?.risk_level || 'low'" /></b></div>
    <div class="meta"><span>金额阈值</span><b class="mono">{{ context?.permissions?.amount_threshold ?? "—" }}</b></div>
  </div>

  <div class="split" style="margin: 16px 0">
    <button class="btn btn-primary" @click="install">装配技能</button>
    <button class="btn btn-ghost" @click="copyFrom">从其他员工复制</button>
  </div>

  <div class="section-label">已装配</div>
  <div v-if="skills.length" class="table-wrap">
    <table>
      <thead>
        <tr><th>技能</th><th>版本</th><th>状态</th><th>来源</th><th>工具</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="item in skills" :key="item.id">
          <td>
            <div class="cell-main">
              <b>{{ item.package_name }}</b>
              <small class="mono">{{ item.skill_code }}</small>
            </div>
          </td>
          <td class="mono">v{{ item.version }}</td>
          <td><StatusPill :status="item.status" /></td>
          <td><span class="tag">{{ item.source }}</span></td>
          <td class="mono muted">{{ (item.tool_codes || []).join(", ") || "—" }}</td>
          <td>
            <div class="row-actions">
              <button class="btn btn-sm" @click="upgrade(item)">升级</button>
              <button class="btn btn-sm btn-ghost" @click="toggle(item)">
                {{ item.status === "active" ? "停用" : "启用" }}
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else class="muted" style="font-size: 12px">还没有装配技能，去技能市场安装。</div>

  <div class="section-label">注入提示词的技能上下文</div>
  <pre class="code">{{ context?.context || "（未装配技能）" }}</pre>

  <div class="section-label">AI 组合推荐</div>
  <div class="split">
    <input
      v-model="recommendNeed"
      class="filter-input"
      placeholder="例如：能自己催回款、生成月报"
      @keyup.enter="recommend"
    />
    <select v-model="recommendMode" class="filter-select">
      <option value="rule">规则推荐</option>
      <option value="llm">LLM 推荐</option>
    </select>
    <button class="btn btn-ghost" @click="recommend">推荐技能</button>
  </div>
  <div v-if="recommendations.length" class="recommend-list">
    <div v-for="item in recommendations" :key="item.code" class="recommend">
      <div>
        <b>{{ item.name }}</b>
        <span class="tag" style="margin-left: 6px">{{ item.category }}</span>
        <span v-if="item.source" class="tag" style="margin-left: 6px">
          {{ item.source === "llm" ? "LLM" : "规则" }}
        </span>
        <small class="muted"> · {{ item.reason }}</small>
      </div>
      <button class="btn btn-sm btn-primary" @click="installCode(item.code)">安装</button>
    </div>
  </div>
</template>

<style scoped>
.filter-input {
  flex: 1;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
}
.recommend-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.recommend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  font-size: 12.5px;
}
</style>
