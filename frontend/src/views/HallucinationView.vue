<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface HallucinationCheck {
  id: number;
  employee_id?: number | null;
  question?: string | null;
  answer: string;
  sources: string[];
  score: number;
  grounded: boolean;
  details: Array<{ sentence: string; support: number; grounded: boolean }>;
  created_at: string;
}

const form = reactive({
  employee_id: "",
  question: "",
  answer: "",
  sources: "",
});
const employees = ref<Employee[]>([]);
const checks = ref<HallucinationCheck[]>([]);
const result = ref<HallucinationCheck | null>(null);
const checking = ref(false);

const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [employeeData, checkData] = await Promise.all([
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
      api.get<Paged<HallucinationCheck>>("/hallucination/checks?page_size=50"),
    ]);
    employees.value = employeeData.items;
    checks.value = checkData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function check(): Promise<void> {
  const sources = form.sources
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!form.answer.trim() || !sources.length) {
    toast.push("请填写答案与至少一条来源", "error");
    return;
  }
  checking.value = true;
  try {
    result.value = await api.post<any>("/hallucination/check", {
      employee_id: form.employee_id ? Number(form.employee_id) : null,
      question: form.question || null,
      answer: form.answer,
      sources,
    });
    toast.push(
      result.value?.grounded ? "答案有来源支撑" : "检测到未支撑内容",
      result.value?.grounded ? "success" : "error",
    );
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "检测失败", "error");
  } finally {
    checking.value = false;
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="governance / hallucination"
    title="幻觉检测"
    sub="按答案句子与来源的证据重合度估算支撑度，定位未支撑表述。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
    </template>
  </PageHeader>

  <div class="grid-equal">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">检测</div>
          <div class="panel-sub">来源每行一条；分数越高越有据可依。</div>
        </div>
      </div>
      <div class="field">
        <label>关联员工</label>
        <select v-model="form.employee_id">
          <option value="">不关联</option>
          <option v-for="item in employees" :key="item.id" :value="String(item.id)">
            {{ item.name }} · {{ item.code }}
          </option>
        </select>
      </div>
      <div class="field" style="margin-top: 10px">
        <label>问题（可选）</label>
        <input v-model="form.question" placeholder="退款政策是什么？" />
      </div>
      <div class="field" style="margin-top: 10px">
        <label>答案</label>
        <textarea v-model="form.answer" rows="6" placeholder="粘贴需要核查的答案" />
      </div>
      <div class="field" style="margin-top: 10px">
        <label>来源（每行一条）</label>
        <textarea v-model="form.sources" rows="6" placeholder="粘贴知识库原文/检索结果" />
      </div>
      <button class="btn btn-primary" style="margin-top: 14px" :disabled="checking" @click="check">
        {{ checking ? "检测中…" : "开始检测" }}
      </button>

      <template v-if="result">
        <div class="section-label">检测结果</div>
        <div class="alert-banner" :style="result.grounded ? '' : 'border-color: rgba(239,106,91,.4)'">
          <div>
            <b>{{ result.grounded ? "有支撑" : "存在未支撑内容" }}</b>
            · score {{ result.score }} · 句子 {{ result.details?.length || 0 }}
          </div>
        </div>
        <div v-if="result.details?.length" class="table-wrap" style="margin-top: 10px">
          <table>
            <thead><tr><th>句子</th><th>支撑度</th><th>结论</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in result.details" :key="index">
                <td>{{ item.sentence }}</td>
                <td class="mono">{{ item.support }}</td>
                <td>
                  <StatusPill :status="item.grounded ? 'succeeded' : 'failed'" :text="item.grounded ? '支撑' : '未支撑'" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">检测记录</div>
          <div class="panel-sub">最近 50 条</div>
        </div>
      </div>
      <div v-if="checks.length" class="table-wrap">
        <table>
          <thead><tr><th>答案</th><th>分数</th><th>结论</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="item in checks" :key="item.id">
              <td>{{ item.answer.slice(0, 60) }}</td>
              <td class="mono">{{ item.score }}</td>
              <td>
                <StatusPill :status="item.grounded ? 'succeeded' : 'failed'" :text="item.grounded ? '支撑' : '未支撑'" />
              </td>
              <td class="muted">{{ fmtDate(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12px">还没有检测记录。</div>
      <div class="section-label">原始结果</div>
      <JsonBlock :value="result || {}" />
    </div>
  </div>
</template>
