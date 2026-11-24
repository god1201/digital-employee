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

const detail = ref<any>(null);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    detail.value = await api.get(`/interventions/${props.id}`);
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function createArtifact(): void {
  modal.openForm({
    title: "把接管增量提炼为学习工件",
    sub: "人工修改是最有价值的学习信号；工件默认进入审批队列。",
    wide: true,
    fields: [
      { name: "attribution", label: "归因", required: true, placeholder: "规划错误 / 风格不符 / 知识缺失" },
      {
        name: "target_layer",
        label: "目标层",
        type: "select",
        options: [
          { value: "procedural_memory", label: "程序记忆（SOP）" },
          { value: "semantic_memory", label: "语义记忆（事实）" },
          { value: "persona_layer", label: "人格层（风格）" },
          { value: "tool_config", label: "工具配置" },
          { value: "skill_gap", label: "能力缺口" },
        ],
        value: "procedural_memory",
      },
      {
        name: "risk",
        label: "风险",
        type: "select",
        options: ["low", "medium", "high"],
        value: "medium",
      },
      {
        name: "scope",
        label: "作用域",
        type: "select",
        options: [
          { value: "personal", label: "个人经验（仅本员工）" },
          { value: "team", label: "团队共享（主管审核）" },
          { value: "organization", label: "组织知识（走治理流程）" },
        ],
        value: "personal",
      },
      { name: "proposal", label: "建议方案（JSON）", type: "json", value: { action: "update_sop", content: "" } },
      { name: "evidence", label: "证据（每行一条）", type: "textarea", rows: 3 },
    ],
    submitLabel: "创建学习工件",
    onSubmit: async (values) => {
      const evidence = String(values.evidence || "")
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      await api.post(`/interventions/${props.id}/artifact`, {
        attribution: values.attribution,
        target_layer: values.target_layer,
        risk: values.risk,
        scope: values.scope,
        proposal: values.proposal,
        evidence,
      });
      toast.push("学习工件已进入审批队列");
      drawer.close();
      props.onChanged?.();
    },
  });
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>接管增量 #{{ id }}</h3>
      <p>{{ employeeName || "—" }} · 人工终稿 vs 原输出</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>来源</span><b class="mono">{{ detail.source_type }}</b></div>
      <div class="meta"><span>任务实例</span><b class="mono">#{{ detail.instance_id ?? "—" }}</b></div>
      <div class="meta"><span>步骤</span><b class="mono">#{{ detail.step_id ?? "—" }}</b></div>
      <div class="meta"><span>变更数</span><b>{{ detail.summary?.total ?? detail.diff?.length ?? 0 }}</b></div>
      <div class="meta"><span>采集时间</span><b>{{ fmtDate(detail.created_at) }}</b></div>
    </div>

    <div v-if="detail.comment" class="alert-banner" style="margin-bottom: 16px">
      <div><b>人工备注</b> · {{ detail.comment }}</div>
    </div>

    <div class="section-label">DIFF · 原输出 → 终稿</div>
    <div v-if="detail.diff?.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>路径</th><th>动作</th><th>原值</th><th>终稿</th></tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in detail.diff" :key="index">
            <td class="mono">{{ item.path }}</td>
            <td><span class="tag">{{ item.op }}</span></td>
            <td class="mono muted">{{ JSON.stringify(item.before) }}</td>
            <td class="mono">{{ JSON.stringify(item.after) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">无结构化差异（可能仅记录批注）</div>

    <div class="section-label">原始输出</div>
    <JsonBlock :value="detail.original_output" />

    <div class="section-label">人工终稿</div>
    <JsonBlock :value="detail.final_output" />

    <div class="split" style="margin-top: 18px">
      <button class="btn btn-primary" @click="createArtifact">提炼为学习工件</button>
      <button class="btn btn-ghost" @click="drawer.close()">关闭</button>
    </div>
  </template>
</template>
