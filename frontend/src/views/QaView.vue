<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

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

interface QaRule {
  id: number;
  name: string;
  code: string;
  category: string;
  rule_type: string;
  config: Record<string, unknown>;
  penalty: number;
  blocking: boolean;
  enabled: boolean;
  description: string;
  created_at: string;
}

interface RuleResult {
  name?: string;
  hit?: boolean;
  [key: string]: unknown;
}

interface QaCheck {
  id: number;
  title: string;
  content: string;
  category: string;
  score: number;
  grade: string;
  decision: string;
  rule_results: RuleResult[];
  status: string;
  review_comment?: string | null;
  created_at: string;
}

const rules = ref<QaRule[]>([]);
const checks = ref<QaCheck[]>([]);
const loading = ref(false);

const checkTitle = ref("");
const checkContent = ref("");
const checkCategory = ref("content");
const checking = ref(false);
const checkResult = ref<QaCheck | null>(null);
const checkError = ref("");

const modal = useModalStore();
const toast = useToastStore();

const decisionTone = computed(() => {
  const decision = checkResult.value?.decision;
  if (decision === "reject") return "block";
  if (decision === "review") return "review";
  return "allow";
});

const hitNames = computed(() =>
  (checkResult.value?.rule_results || [])
    .filter((item) => item.hit)
    .map((item) => item.name || "")
    .filter(Boolean)
    .join(" · "),
);

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function decisionStatus(decision: string): string {
  if (decision === "pass") return "allow";
  if (decision === "reject") return "block";
  return "review";
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [ruleData, checkData] = await Promise.all([
      api.get<Paged<QaRule>>("/qa/rules?page_size=200"),
      api.get<Paged<QaCheck>>("/qa/checks?page_size=50"),
    ]);
    rules.value = ruleData.items;
    checks.value = checkData.items;
  } catch (err) {
    toast.push(errorMessage(err, "加载失败"), "error");
  } finally {
    loading.value = false;
  }
}

function openRuleForm(rule?: QaRule): void {
  const editing = Boolean(rule);
  modal.openForm({
    title: editing ? "编辑质检规则" : "新建质检规则",
    sub: "keyword 使用 config.keywords；regex 使用 config.pattern；长度规则使用 config.value。",
    wide: true,
    fields: [
      { name: "name", label: "名称", required: true, placeholder: "违禁词检查", value: rule?.name || "" },
      {
        name: "code",
        label: "编码",
        required: true,
        placeholder: "forbidden_words",
        value: rule?.code || "",
        help: editing ? "编码创建后不可修改" : "仅支持字母、数字、下划线与连字符",
      },
      {
        name: "category",
        label: "类别",
        type: "select",
        options: [
          { value: "content", label: "内容" },
          { value: "service", label: "服务" },
          { value: "text", label: "文本" },
        ],
        value: rule?.category || "content",
      },
      {
        name: "rule_type",
        label: "规则类型",
        type: "select",
        options: ["keyword", "regex", "min_length", "max_length"],
        value: rule?.rule_type || "keyword",
      },
      { name: "penalty", label: "扣分", type: "number", value: rule?.penalty ?? 20 },
      {
        name: "blocking",
        label: "命中即阻断",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
        value: rule ? String(rule.blocking) : "false",
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
      {
        name: "config",
        label: "规则配置 JSON",
        type: "json",
        full: true,
        value: rule?.config || { keywords: ["违禁"] },
      },
      { name: "description", label: "说明", full: true, type: "textarea", rows: 2, value: rule?.description || "" },
    ],
    submitLabel: editing ? "保存" : "创建规则",
    onSubmit: async (values) => {
      const payload = {
        name: values.name,
        code: values.code,
        category: values.category,
        rule_type: values.rule_type,
        penalty: Number(values.penalty || 10),
        blocking: values.blocking === "true",
        enabled: values.enabled === "true",
        config: values.config,
        description: values.description,
      };
      if (rule) {
        await api.patch(`/qa/rules/${rule.id}`, {
          name: values.name,
          category: values.category,
          rule_type: values.rule_type,
          penalty: Number(values.penalty || 10),
          blocking: values.blocking === "true",
          enabled: values.enabled === "true",
          config: values.config,
          description: values.description,
        });
        toast.push("质检规则已更新");
      } else {
        await api.post("/qa/rules", payload);
        toast.push("质检规则已创建");
      }
      await load();
    },
  });
}

async function removeRule(row: QaRule): Promise<void> {
  if (!window.confirm(`确认删除质检规则「${row.name}」？`)) return;
  try {
    await api.delete(`/qa/rules/${row.id}`);
    toast.push("规则已删除");
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "删除失败"), "error");
  }
}

async function runCheck(): Promise<void> {
  if (!checkTitle.value.trim() || !checkContent.value.trim()) return;
  checking.value = true;
  checkError.value = "";
  checkResult.value = null;
  try {
    checkResult.value = await api.post<QaCheck>("/qa/checks", {
      title: checkTitle.value,
      content: checkContent.value,
      category: checkCategory.value,
    });
    await load();
  } catch (err) {
    checkError.value = errorMessage(err, "质检失败");
  } finally {
    checking.value = false;
  }
}

async function review(row: QaCheck, decision: "pass" | "reject"): Promise<void> {
  const comment = window.prompt("复核备注（可选）");
  if (comment === null) return;
  try {
    await api.post(`/qa/checks/${row.id}/review`, { decision, comment });
    toast.push("复核已提交");
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "复核失败"), "error");
  }
}
</script>

<template>
  <PageHeader
    eyebrow="business / quality"
    title="质检"
    sub="规则化评分、分级处置与人工复核。"
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
          <div class="panel-title">质检规则</div>
          <div class="panel-sub">{{ rules.length }} 条</div>
        </div>
      </div>
      <DataTable
        :rows="rules"
        :columns="[
          {
            label: '规则',
            format: (row) =>
              `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>`,
          },
          { label: '类型', format: (row) => `<span class='tag'>${esc(row.rule_type)}</span>` },
          { label: '扣分', format: (row) => `<span class='mono'>-${row.penalty}</span>` },
          { label: '阻断', key: 'blocking' },
          { label: '状态', key: 'enabled' },
          { label: '', key: 'actions' },
        ]"
        empty-text="还没有质检规则"
      >
        <template #cell-blocking="{ row }">
          <StatusPill :status="row.blocking ? 'high' : 'low'" :text="row.blocking ? '阻断' : '不阻断'" />
        </template>
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
          <div class="panel-title">即时质检</div>
          <div class="panel-sub">按启用规则扣分，输出等级与处置建议。</div>
        </div>
      </div>
      <form @submit.prevent="runCheck">
        <div class="field">
          <label>标题</label>
          <input v-model="checkTitle" placeholder="内容标题" required />
        </div>
        <div class="field" style="margin-top: 10px">
          <label>内容</label>
          <textarea v-model="checkContent" rows="6" required placeholder="粘贴待质检文本..." />
        </div>
        <div class="field" style="margin-top: 10px">
          <label>类别</label>
          <select v-model="checkCategory">
            <option value="content">内容</option>
            <option value="service">服务</option>
            <option value="text">文本</option>
          </select>
        </div>
        <button class="btn btn-primary" type="submit" style="margin-top: 14px" :disabled="checking">
          <AppIcon name="check" />{{ checking ? "质检中..." : "开始质检" }}
        </button>
      </form>

      <div v-if="checking" class="skeleton" style="height: 100px; margin-top: 14px" />
      <EmptyState v-else-if="checkError" :text="checkError" />
      <div v-else-if="checkResult" class="decision-card" :class="decisionTone">
        <div>
          <div class="verdict">{{ checkResult.grade }} · {{ checkResult.decision }}</div>
          <div class="score">score {{ checkResult.score }}</div>
        </div>
        <div class="muted">{{ hitNames || "未触发规则" }}</div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">质检记录</div>
        <div class="panel-sub">最近 50 条 · 支持人工复核</div>
      </div>
    </div>
    <DataTable
      :rows="checks"
      :columns="[
        {
          label: '内容',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.title)}</b><small class='truncate'>${esc(String(row.content).slice(0, 80))}</small></div>`,
        },
        { label: '得分', format: (row) => `<span class='mono'>${row.score}</span>` },
        { label: '等级', format: (row) => `<span class='tag'>${esc(row.grade)}</span>` },
        { label: '判定', key: 'decision' },
        { label: '状态', key: 'status' },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有质检记录"
    >
      <template #cell-decision="{ row }">
        <StatusPill :status="decisionStatus(row.decision)" :text="row.decision" />
      </template>
      <template #cell-status="{ row }">
        <StatusPill :status="row.status === 'pending' ? 'pending' : 'acked'" :text="row.status" />
      </template>
      <template #cell-actions="{ row }">
        <div v-if="row.status === 'pending'" class="row-actions">
          <button class="btn btn-sm" @click="review(row, 'pass')">通过</button>
          <button class="btn btn-sm btn-danger" @click="review(row, 'reject')">驳回</button>
        </div>
        <span v-else class="dim mono">{{ row.review_comment || "已复核" }}</span>
      </template>
    </DataTable>
  </div>
</template>
