<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface RiskRule {
  id: number;
  name: string;
  category: string;
  keywords: string[];
  action: string;
  severity: string;
  enabled: boolean;
  description: string;
  created_at: string;
}

interface MatchedRule {
  id?: number;
  name?: string;
  action?: string;
  severity?: string;
}

interface RiskCheck {
  id: number;
  content: string;
  category: string;
  decision: string;
  score: number;
  matched_rules: MatchedRule[];
  created_at: string;
}

const rules = ref<RiskRule[]>([]);
const checks = ref<RiskCheck[]>([]);
const loading = ref(false);

const checkContent = ref("");
const checkCategory = ref("content");
const checking = ref(false);
const checkResult = ref<RiskCheck | null>(null);
const checkError = ref("");

const modal = useModalStore();
const toast = useToastStore();

function categoryLabel(value: string): string {
  return value === "business" ? "业务风控" : "内容风控";
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function matchedNames(row: RiskCheck): string {
  return (row.matched_rules || [])
    .map((rule) => rule.name || "")
    .filter(Boolean)
    .join(" / ");
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [ruleData, checkData] = await Promise.all([
      api.get<Paged<RiskRule>>("/risk/rules?page_size=200"),
      api.get<Paged<RiskCheck>>("/risk/checks?page_size=20"),
    ]);
    rules.value = ruleData.items;
    checks.value = checkData.items;
  } catch (err) {
    toast.push(errorMessage(err, "加载失败"), "error");
  } finally {
    loading.value = false;
  }
}

function openRuleForm(rule?: RiskRule): void {
  const editing = Boolean(rule);
  modal.openForm({
    title: editing ? "编辑风控规则" : "新建风控规则",
    sub: editing ? "修改关键词与处置策略后立即生效。" : "命中关键词后按处置级别阻断、复核或放行。",
    fields: [
      { name: "name", label: "名称", required: true, placeholder: "敏感词拦截", value: rule?.name || "" },
      {
        name: "category",
        label: "类别",
        type: "select",
        options: [
          { value: "content", label: "内容风控" },
          { value: "business", label: "业务风控" },
        ],
        value: rule?.category || "content",
      },
      {
        name: "keywords",
        label: "关键词（逗号分隔）",
        required: true,
        placeholder: "赌博,违禁,诈骗",
        value: (rule?.keywords || []).join(","),
      },
      {
        name: "action",
        label: "处置",
        type: "select",
        options: ["review", "block", "allow"],
        value: rule?.action || "review",
      },
      {
        name: "severity",
        label: "级别",
        type: "select",
        options: ["low", "medium", "high"],
        value: rule?.severity || "medium",
      },
      {
        name: "enabled",
        label: "启用",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
        value: rule ? String(rule.enabled) : "true",
      },
      { name: "description", label: "说明", full: true, type: "textarea", rows: 2, value: rule?.description || "" },
    ],
    submitLabel: editing ? "保存" : "创建规则",
    onSubmit: async (values) => {
      const payload = {
        name: values.name,
        category: values.category,
        keywords: String(values.keywords)
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        action: values.action,
        severity: values.severity,
        enabled: values.enabled === "true",
        description: values.description,
      };
      if (rule) {
        await api.patch(`/risk/rules/${rule.id}`, payload);
        toast.push("风控规则已更新");
      } else {
        await api.post("/risk/rules", payload);
        toast.push("风控规则已创建");
      }
      await load();
    },
  });
}

async function removeRule(row: RiskRule): Promise<void> {
  if (!window.confirm(`确认删除风控规则「${row.name}」？`)) return;
  try {
    await api.delete(`/risk/rules/${row.id}`);
    toast.push("规则已删除");
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "删除失败"), "error");
  }
}

async function runCheck(): Promise<void> {
  if (!checkContent.value.trim()) return;
  checking.value = true;
  checkError.value = "";
  checkResult.value = null;
  try {
    checkResult.value = await api.post<RiskCheck>("/risk/check", {
      content: checkContent.value,
      category: checkCategory.value,
    });
    await load();
  } catch (err) {
    checkError.value = errorMessage(err, "检查失败");
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <PageHeader
    eyebrow="governance / risk"
    title="内容风控"
    sub="关键词规则 + 分级处置，阻断 / 复核 / 放行。"
  >
    <template #actions>
      <button class="btn btn-ghost" :disabled="loading" @click="load">
        <AppIcon name="refresh" />刷新
      </button>
      <button class="btn btn-primary" @click="openRuleForm()"><AppIcon name="plus" />新建规则</button>
    </template>
  </PageHeader>

  <div class="grid-equal">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">风控规则</div>
          <div class="panel-sub">{{ rules.length }} 条规则</div>
        </div>
      </div>
      <DataTable
        :rows="rules"
        :columns="[
          {
            label: '规则',
            format: (row) =>
              `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(categoryLabel(row.category))}</small></div>`,
          },
          { label: '关键词', format: (row) => `<span class='mono'>${esc((row.keywords || []).join(' / '))}</span>` },
          { label: '处置', key: 'action' },
          { label: '级别', key: 'severity' },
          { label: '状态', key: 'enabled' },
          { label: '', key: 'actions' },
        ]"
        empty-text="还没有风控规则"
      >
        <template #cell-action="{ row }"><StatusPill :status="row.action" /></template>
        <template #cell-severity="{ row }"><StatusPill :status="row.severity" /></template>
        <template #cell-enabled="{ row }">
          <StatusPill :status="row.enabled ? 'active' : 'disabled'" :text="row.enabled ? 'active' : 'disabled'" />
        </template>
        <template #cell-actions="{ row }">
          <div class="row-actions">
            <button class="btn btn-sm" @click="openRuleForm(row)">编辑</button>
            <button class="btn btn-sm btn-ghost" @click="removeRule(row)">删除</button>
          </div>
        </template>
      </DataTable>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">即时检查</div>
          <div class="panel-sub">输入文本，命中规则后给出处置建议。</div>
        </div>
      </div>
      <form @submit.prevent="runCheck">
        <div class="field">
          <label>检查内容</label>
          <textarea
            v-model="checkContent"
            rows="7"
            required
            placeholder="粘贴待审核的文案、评论或商品描述..."
          />
        </div>
        <div class="field" style="margin-top: 12px">
          <label>类别</label>
          <select v-model="checkCategory">
            <option value="content">内容风控</option>
            <option value="business">业务风控</option>
          </select>
        </div>
        <button class="btn btn-primary" type="submit" style="margin-top: 14px" :disabled="checking">
          <AppIcon name="shield" />{{ checking ? "检查中..." : "执行检查" }}
        </button>
      </form>

      <div v-if="checking" class="skeleton" style="height: 80px; margin-top: 14px" />
      <EmptyState v-else-if="checkError" :text="checkError" />
      <div v-else-if="checkResult" class="decision-card" :class="checkResult.decision">
        <div>
          <div class="verdict">{{ checkResult.decision }}</div>
          <div class="score">score {{ checkResult.score }}</div>
        </div>
        <div class="muted">
          {{ matchedNames(checkResult) || "未命中规则" }}
        </div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">检查记录</div>
        <div class="panel-sub">最近 20 条</div>
      </div>
    </div>
    <DataTable
      :rows="checks"
      :columns="[
        { label: '内容', format: (row) => `<div class='truncate'>${esc(row.content)}</div>` },
        { label: '类别', format: (row) => `<span class='tag'>${esc(categoryLabel(row.category))}</span>` },
        { label: '判定', key: 'decision' },
        { label: '评分', format: (row) => `<span class='mono'>${row.score}</span>` },
        { label: '命中', format: (row) => `<span class='mono'>${esc(matchedNames(row) || '—')}</span>` },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
      ]"
      empty-text="还没有检查记录"
    >
      <template #cell-decision="{ row }"><StatusPill :status="row.decision" /></template>
    </DataTable>
  </div>
</template>
