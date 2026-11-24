<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

const props = defineProps<{ employee: Employee; onChanged?: () => void }>();

const tab = ref<"import" | "examples">("import");
const knowledgeBases = ref<any[]>([]);
const examples = ref<any[]>([]);
const status = ref<any>(null);
const extracted = ref<any>(null);
const loading = ref(false);

const form = reactive({
  source_type: "jd",
  text: "",
  title: "",
  knowledge_base_id: "",
  apply_contract: "true",
});

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [bases, exampleData, statusData] = await Promise.all([
      api.get<any>("/knowledge-bases?page_size=200"),
      api.get<any[]>(`/digital-employees/${props.employee.id}/few-shot-examples`),
      api.get<any>(`/digital-employees/${props.employee.id}/onboarding/status`),
    ]);
    knowledgeBases.value = bases.items;
    examples.value = exampleData;
    status.value = statusData;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function importMaterial(): Promise<void> {
  if (!form.text.trim()) {
    toast.push("请粘贴 JD / SOP 内容", "error");
    return;
  }
  loading.value = true;
  try {
    const result = await api.post<any>(
      `/digital-employees/${props.employee.id}/onboarding/import`,
      {
        source_type: form.source_type,
        text: form.text,
        title: form.title || null,
        knowledge_base_id: form.knowledge_base_id
          ? Number(form.knowledge_base_id)
          : null,
        apply_contract: form.apply_contract === "true",
      },
    );
    extracted.value = result;
    toast.push(`已抽取契约草稿（${result.source}）`);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "导入失败", "error");
  } finally {
    loading.value = false;
  }
}

function addExample(): void {
  modal.openForm({
    title: "新增示范案例",
    sub: "输入一条真实工单/对话与期望输出，会作为 Few-shot 注入规划与 LLM 步骤。",
    wide: true,
    fields: [
      { name: "name", label: "名称", placeholder: "催款邮件示例" },
      { name: "input", label: "输入", type: "textarea", required: true, rows: 3 },
      { name: "output", label: "期望输出", type: "textarea", required: true, rows: 4 },
      { name: "tags", label: "标签（每行一个）", type: "textarea", rows: 2 },
    ],
    submitLabel: "保存案例",
    onSubmit: async (values) => {
      await api.post(`/digital-employees/${props.employee.id}/few-shot-examples`, {
        name: values.name || "",
        input: values.input,
        output: values.output,
        tags: String(values.tags || "")
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
        source: "onboarding",
      });
      toast.push("示范案例已保存");
      await load();
    },
  });
}

function bulkExamples(): void {
  modal.openForm({
    title: "批量导入入职案例",
    sub: "粘贴 JSON 数组，每项包含 input/output，可选 name/tags。",
    wide: true,
    fields: [
      {
        name: "examples",
        label: "案例数组（JSON）",
        type: "json",
        value: [{ input: "客户催回款", output: "已生成对账单并附明细" }],
      },
    ],
    submitLabel: "批量导入",
    onSubmit: async (values) => {
      if (!Array.isArray(values.examples) || !values.examples.length) {
        throw new Error("examples 必须是非空数组");
      }
      const result = await api.post<any>(
        `/digital-employees/${props.employee.id}/onboarding/examples`,
        { examples: values.examples },
      );
      toast.push(`已导入 ${result.created} 条案例`);
      await load();
    },
  });
}

async function disableExample(row: any): Promise<void> {
  if (!confirm("确认停用该示范案例？")) return;
  try {
    await api.delete(`/few-shot-examples/${row.id}`);
    toast.push("已停用");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>{{ employee.name }} · 入职引导</h3>
      <p>{{ employee.code }} · 读岗 / 看案例 / 契约草稿</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'import' }" @click="tab = 'import'">
      入职资料
    </button>
    <button class="tab" :class="{ active: tab === 'examples' }" @click="tab = 'examples'">
      示范案例 <span class="dim">{{ examples.length }}</span>
    </button>
  </div>

  <template v-if="tab === 'import'">
    <div class="meta-grid">
      <div class="meta">
        <span>契约</span>
        <b>{{ status?.contract?.status || "未配置" }}</b>
      </div>
      <div class="meta"><span>案例</span><b>{{ status?.few_shot_count ?? 0 }}</b></div>
      <div class="meta">
        <span>认证</span>
        <b>{{ status?.certification?.level || "未认证" }}</b>
      </div>
    </div>

    <div class="section-label">JD / SOP</div>
    <div class="form-grid">
      <div class="field">
        <label>资料类型</label>
        <select v-model="form.source_type">
          <option value="jd">岗位说明书（JD）</option>
          <option value="sop">SOP / 作业规范</option>
          <option value="policy">制度 / 政策</option>
        </select>
      </div>
      <div class="field">
        <label>是否生成契约草稿</label>
        <select v-model="form.apply_contract">
          <option value="true">生成草稿（需管理员）</option>
          <option value="false">只抽取不写入</option>
        </select>
      </div>
      <div class="field">
        <label>同时导入知识库</label>
        <select v-model="form.knowledge_base_id">
          <option value="">不导入</option>
          <option v-for="base in knowledgeBases" :key="base.id" :value="String(base.id)">
            {{ base.name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>文档标题</label>
        <input v-model="form.title" placeholder="入职资料 · 应收账款专员" />
      </div>
      <div class="field full">
        <label>资料正文</label>
        <textarea
          v-model="form.text"
          rows="10"
          placeholder="粘贴 JD / SOP / 制度原文；系统会抽取岗位职责、禁止事项与必须请示事项。"
        />
      </div>
    </div>

    <div class="split" style="margin-top: 14px">
      <button class="btn btn-primary" :disabled="loading" @click="importMaterial">
        {{ loading ? "抽取中…" : "抽取并生成草稿" }}
      </button>
    </div>

    <template v-if="extracted">
      <div class="section-label">抽取结果</div>
      <JsonBlock :value="extracted" />
    </template>
  </template>

  <template v-else>
    <div class="split" style="margin: 12px 0">
      <button class="btn btn-primary" @click="addExample">新增案例</button>
      <button class="btn btn-ghost" @click="bulkExamples">批量导入</button>
    </div>

    <div v-if="examples.length" class="table-wrap">
      <table>
        <thead><tr><th>案例</th><th>标签</th><th>状态</th><th>创建</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in examples" :key="item.id">
            <td>
              <div class="cell-main">
                <b>{{ item.name || item.input.slice(0, 40) }}</b>
                <small>{{ item.input.slice(0, 80) }}</small>
              </div>
            </td>
            <td class="mono muted">{{ (item.tags || []).join(", ") || "—" }}</td>
            <td>{{ item.enabled ? "启用" : "停用" }}</td>
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
            <td>
              <button class="btn btn-sm btn-danger" @click="disableExample(item)">停用</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">还没有示范案例。</div>

    <div class="section-label">将注入提示词的 Few-shot 上下文</div>
    <pre class="code">{{ status?.few_shot_context || "（暂无）" }}</pre>
  </template>
</template>
