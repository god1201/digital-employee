<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ code: string; onChanged?: () => void }>();

const detail = ref<any>(null);
const employees = ref<any[]>([]);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

function lines(value: unknown): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function load(): Promise<void> {
  try {
    const [packageData, employeeData] = await Promise.all([
      api.get<any>(`/skill-packages/${encodeURIComponent(props.code)}`),
      api.get<any>("/digital-employees?page_size=200"),
    ]);
    detail.value = packageData;
    employees.value = employeeData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function install(): void {
  if (!detail.value) return;
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: `安装 ${detail.value.name}`,
    sub: `安装 v${detail.value.version}，自动解析依赖并返回权限并集。`,
    fields: [
      {
        name: "employee_id",
        label: "安装到员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
    ],
    submitLabel: "安装",
    onSubmit: async (values) => {
      const result = await api.post<any>(
        `/digital-employees/${values.employee_id}/skills`,
        { code: props.code },
      );
      toast.push(`已安装 ${result.installed.length} 个技能（含依赖）`);
      for (const warning of result.warnings || []) toast.push(warning, "info");
      props.onChanged?.();
    },
  });
}

function createVersion(): void {
  if (!detail.value) return;
  modal.openForm({
    title: `创建新版本 · ${detail.value.name}`,
    sub: "新版本为草稿；发布后员工可一键升级，升级前会跑评估回归。",
    wide: true,
    fields: [
      { name: "name", label: "名称", value: detail.value.name },
      { name: "description", label: "描述", type: "textarea", rows: 2, value: detail.value.description },
      { name: "algorithm", label: "算法能力", value: detail.value.algorithm },
      { name: "prompt_template", label: "提示词", type: "textarea", rows: 3, value: detail.value.prompt_template },
      {
        name: "tool_codes",
        label: "工具编码（每行一个）",
        type: "textarea",
        rows: 2,
        value: (detail.value.tool_codes || []).join("\n"),
      },
      {
        name: "dependencies",
        label: "依赖（JSON）",
        type: "json",
        value: detail.value.dependencies || [],
      },
      {
        name: "conflicts_with",
        label: "冲突技能（每行一个）",
        type: "textarea",
        rows: 2,
        value: (detail.value.conflicts_with || []).join("\n"),
      },
      {
        name: "permissions",
        label: "最小权限（JSON）",
        type: "json",
        value: detail.value.permissions || {},
      },
      {
        name: "common_combos",
        label: "常见组合（每行一个）",
        type: "textarea",
        rows: 2,
        value: (detail.value.common_combos || []).join("\n"),
      },
      {
        name: "tags",
        label: "标签（每行一个）",
        type: "textarea",
        rows: 2,
        value: (detail.value.tags || []).join("\n"),
      },
    ],
    submitLabel: "创建草稿版本",
    onSubmit: async (values) => {
      await api.post(`/skill-packages/${encodeURIComponent(props.code)}/versions`, {
        name: values.name,
        description: values.description,
        algorithm: values.algorithm,
        prompt_template: values.prompt_template,
        tool_codes: lines(values.tool_codes),
        dependencies: values.dependencies || [],
        conflicts_with: lines(values.conflicts_with),
        permissions: values.permissions || {},
        common_combos: lines(values.common_combos),
        tags: lines(values.tags),
      });
      toast.push("新版本草稿已创建");
      await load();
      props.onChanged?.();
    },
  });
}

async function publish(version: any): Promise<void> {
  try {
    await api.post(`/skill-packages/${version.id}/publish`, {});
    toast.push(`v${version.version} 已发布`);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "发布失败", "error");
  }
}

async function deprecate(): Promise<void> {
  if (!detail.value || !confirm(`确认下架 ${detail.value.code} v${detail.value.version}？`)) return;
  try {
    await api.delete(`/skill-packages/${detail.value.id}`);
    toast.push("技能包版本已下架");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "下架失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ detail?.name || code }}</h3>
      <p><span class="mono">{{ code }}</span> · 技能包五件套与版本</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>版本</span><b class="mono">v{{ detail.version }}</b></div>
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>分类</span><b>{{ detail.category }}</b></div>
      <div class="meta"><span>来源</span><b>{{ detail.is_builtin ? "平台内置" : "自定义" }}</b></div>
      <div class="meta"><span>只读</span><b>{{ detail.permissions?.read_only ? "是" : "否" }}</b></div>
      <div class="meta"><span>风险</span><b><StatusPill :status="detail.permissions?.risk_level || 'low'" /></b></div>
      <div class="meta"><span>金额阈值</span><b class="mono">{{ detail.permissions?.amount_threshold ?? "—" }}</b></div>
      <div class="meta"><span>创建</span><b>{{ fmtDate(detail.created_at) }}</b></div>
    </div>

    <div class="split" style="margin: 16px 0">
      <button v-if="detail.status === 'published'" class="btn btn-primary" @click="install">
        安装到员工
      </button>
      <button v-if="!detail.is_builtin" class="btn btn-ghost" @click="createVersion">新建版本</button>
      <button v-if="!detail.is_builtin" class="btn btn-danger" @click="deprecate">下架</button>
    </div>

    <div class="section-label">说明</div>
    <p class="muted" style="font-size: 12.5px; line-height: 1.8">
      {{ detail.description || "无" }}
    </p>

    <div class="section-label">算法与提示词</div>
    <div class="tag" style="margin-bottom: 8px">{{ detail.algorithm || "未声明算法" }}</div>
    <JsonBlock :value="{ prompt_template: detail.prompt_template }" />

    <div class="section-label">工具与知识库</div>
    <div class="split">
      <span v-for="tool in detail.tool_codes || []" :key="tool" class="tag">{{ tool }}</span>
      <span v-for="kb in detail.knowledge_base_ids || []" :key="`kb-${kb}`" class="tag">KB #{{ kb }}</span>
      <span v-if="!(detail.tool_codes || []).length && !(detail.knowledge_base_ids || []).length" class="muted">
        未声明
      </span>
    </div>

    <div class="section-label">依赖与冲突</div>
    <JsonBlock :value="{ dependencies: detail.dependencies, conflicts_with: detail.conflicts_with }" />

    <div class="section-label">常见组合</div>
    <div class="split">
      <span v-for="code in detail.common_combos || []" :key="code" class="tag">{{ code }}</span>
      <span v-if="!(detail.common_combos || []).length" class="muted">未声明</span>
    </div>

    <div class="section-label">版本历史</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>版本</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in detail.versions || []" :key="item.id">
            <td class="mono">v{{ item.version }}</td>
            <td><StatusPill :status="item.status" /></td>
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
            <td>
              <button
                v-if="item.status === 'draft' && !detail.is_builtin"
                class="btn btn-sm btn-primary"
                @click="publish(item)"
              >
                发布
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
