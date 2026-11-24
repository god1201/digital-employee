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

const props = defineProps<{
  id: number;
  employeeName?: string;
  onChanged?: () => void;
}>();

const suite = ref<any>(null);
const runs = ref<any[]>([]);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [detail, runPage] = await Promise.all([
      api.get<any>(`/evaluation-suites/${props.id}`),
      api.get<any>(`/evaluation-runs?suite_id=${props.id}&page_size=10`),
    ]);
    suite.value = detail;
    runs.value = runPage.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function addCase(): void {
  modal.openForm({
    title: "新增评估用例",
    sub: "llm 用例由员工作答后按关键词/文本相似度打分；assertion 用例直接比对给定输出。",
    wide: true,
    fields: [
      { name: "name", label: "用例名称", required: true },
      {
        name: "case_type",
        label: "类型",
        type: "select",
        options: [
          { value: "assertion", label: "assertion · 直接比对输出" },
          { value: "llm", label: "llm · 员工作答后打分" },
        ],
        value: "assertion",
      },
      {
        name: "input",
        label: "输入（JSON）",
        type: "json",
        value: { prompt: "" },
        help: "assertion 可传 actual；llm 需要 prompt。",
      },
      {
        name: "expected",
        label: "期望（JSON）",
        type: "json",
        value: { keywords: [], text: "" },
      },
      { name: "weight", label: "权重", type: "number", value: 1 },
    ],
    submitLabel: "新增用例",
    onSubmit: async (values) => {
      await api.post(`/evaluation-suites/${props.id}/cases`, values);
      toast.push("用例已新增");
      await load();
      props.onChanged?.();
    },
  });
}

function run(): void {
  const outputs: Record<string, string> = {};
  for (const item of suite.value?.cases || []) {
    if (item.case_type === "assertion") outputs[String(item.id)] = "";
  }
  modal.openForm({
    title: "执行综合评估",
    sub: "llm 用例会调用员工模型作答；assertion 用例使用这里提供的输出。",
    wide: true,
    fields: [
      {
        name: "outputs",
        label: "assertion 输出（JSON，键为 case_id）",
        type: "json",
        value: outputs,
        help: "仅 assertion 用例需要；llm 用例留空即可。",
      },
    ],
    submitLabel: "开始评估",
    onSubmit: async (values) => {
      const result = await api.post<any>(`/evaluation-suites/${props.id}/run`, {
        outputs: values.outputs || {},
      });
      toast.push(
        result.passed
          ? `评估通过 · ${result.score}`
          : `评估未通过 · ${result.score}（阈值 ${result.threshold}）`,
        result.passed ? "success" : "error",
      );
      await load();
      props.onChanged?.();
    },
  });
}

async function disableSuite(): Promise<void> {
  if (!confirm("确认停用该评估套件？")) return;
  try {
    await api.delete(`/evaluation-suites/${props.id}`);
    toast.push("评估套件已停用");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ suite?.name || "评估套件" }}</h3>
      <p>{{ employeeName || "—" }} · {{ suite?.code || "" }}</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!suite" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>阈值</span><b class="mono">{{ suite.threshold }}</b></div>
      <div class="meta"><span>回归容忍</span><b class="mono">{{ suite.regression_tolerance }}</b></div>
      <div class="meta"><span>生效前强制</span><b>{{ suite.enforce_on_activate ? "是" : "否" }}</b></div>
      <div class="meta"><span>状态</span><b><StatusPill :status="suite.enabled ? 'active' : 'disabled'" /></b></div>
    </div>

    <div class="split" style="margin: 16px 0">
      <button class="btn btn-primary" @click="run">执行评估</button>
      <button class="btn btn-ghost" @click="addCase">新增用例</button>
      <button class="btn btn-danger" @click="disableSuite">停用</button>
    </div>

    <div class="section-label">用例 · {{ suite.cases?.length || 0 }}</div>
    <div v-if="suite.cases?.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>用例</th><th>类型</th><th>权重</th><th>期望</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in suite.cases" :key="item.id">
            <td>
              <div class="cell-main">
                <b>{{ item.name }}</b>
                <small class="mono">#{{ item.id }}</small>
              </div>
            </td>
            <td><span class="tag">{{ item.case_type }}</span></td>
            <td class="mono">{{ item.weight }}</td>
            <td class="mono muted">{{ JSON.stringify(item.expected) }}</td>
            <td><StatusPill :status="item.enabled ? 'active' : 'disabled'" /></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">还没有用例，先新增一条。</div>

    <div class="section-label">最近评估</div>
    <div v-if="runs.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th>触发</th><th>得分</th><th>基线</th><th>变化</th><th>结果</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in runs" :key="item.id">
            <td class="mono">#{{ item.id }}</td>
            <td><span class="tag">{{ item.trigger }}</span></td>
            <td><b>{{ item.score }}</b></td>
            <td class="mono muted">{{ item.baseline_score ?? "—" }}</td>
            <td class="mono">{{ item.delta ?? "—" }}</td>
            <td><StatusPill :status="item.passed ? 'succeeded' : 'failed'" :text="item.passed ? 'passed' : 'failed'" /></td>
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <details v-for="item in runs" :key="`d-${item.id}`" style="margin-top: 8px">
        <summary class="muted" style="cursor: pointer; font-size: 12px">
          #{{ item.id }} 明细{{ item.error ? ` · ${item.error}` : "" }}
        </summary>
        <JsonBlock :value="item.details" />
      </details>
    </div>
    <div v-else class="muted" style="font-size: 12px">还没有评估记录。</div>
  </template>
</template>
