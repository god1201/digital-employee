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
const lineage = ref<any[]>([]);
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [artifact, chain] = await Promise.all([
      api.get<any>(`/learning-artifacts/${props.id}`),
      api.get<any[]>(`/learning-artifacts/${props.id}/lineage`),
    ]);
    detail.value = artifact;
    lineage.value = chain;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function createVersion(): void {
  if (!detail.value) return;
  modal.openForm({
    title: "基于当前工件创建新版本",
    sub: "新版本会挂到版本树上，仍需审批；旧版本保留可回滚。",
    wide: true,
    fields: [
      { name: "attribution", label: "归因", value: detail.value.attribution },
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
        value: detail.value.target_layer,
      },
      { name: "proposal", label: "建议方案（JSON）", type: "json", value: detail.value.proposal || {} },
      {
        name: "evidence",
        label: "证据（每行一条）",
        type: "textarea",
        rows: 3,
        value: (detail.value.evidence || []).join("\n"),
      },
      {
        name: "risk",
        label: "风险",
        type: "select",
        options: ["low", "medium", "high"],
        value: detail.value.risk,
      },
      {
        name: "scope",
        label: "作用域",
        type: "select",
        options: [
          { value: "personal", label: "个人经验" },
          { value: "team", label: "团队共享" },
          { value: "organization", label: "组织知识" },
        ],
        value: detail.value.scope,
      },
    ],
    submitLabel: "创建新版本",
    onSubmit: async (values) => {
      const evidence = String(values.evidence || "")
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      await api.post(`/learning-artifacts/${props.id}/new-version`, {
        ...values,
        evidence,
      });
      toast.push("新版本已创建，进入审批队列");
      await load();
      props.onChanged?.();
    },
  });
}

async function rollout(mode: "shadow" | "canary" | "full"): Promise<void> {
  let traffic = 1;
  if (mode === "canary") {
    const input = window.prompt("金丝雀流量比例（0-1）", "0.1");
    if (input === null) return;
    traffic = Number(input);
    if (!Number.isFinite(traffic)) traffic = 0.1;
  }
  try {
    await api.post(`/learning-artifacts/${props.id}/rollout`, { mode, traffic });
    toast.push(mode === "full" ? "已全量发布" : mode === "canary" ? "已进入金丝雀" : "已进入影子观察");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "发布失败", "error");
  }
}

async function promote(): Promise<void> {
  try {
    const result = await api.post<any>(`/learning-artifacts/${props.id}/promote`, {});
    toast.push(`已推进到 ${result.status}`);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "推进失败", "error");
  }
}

async function share(scope: "team" | "organization"): Promise<void> {
  const note = window.prompt(scope === "team" ? "团队共享说明" : "组织共享说明") ?? "";
  try {
    const result = await api.post<any>(`/learning-artifacts/${props.id}/share`, {
      scope,
      note: note || null,
    });
    toast.push(`共享副本 #${result.id} 已进入审批队列`);
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "共享失败", "error");
  }
}

async function act(action: string, note?: string): Promise<void> {
  try {
    await api.post(`/learning-artifacts/${props.id}/${action}`, note ? { note } : {});
    toast.push("操作已提交");
    await load();
    props.onChanged?.();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function approve(): void {
  const note = window.prompt("审批备注（可选）") ?? "";
  act("approve", note);
}

function reject(): void {
  const note = window.prompt("驳回原因（将回流为负样本）") ?? "";
  act("reject", note);
}

function rollback(): void {
  const note = window.prompt("回滚原因（可选）") ?? "";
  act("rollback", note);
}

onMounted(load);
</script>

<template>
  <div class="drawer-head">
    <div>
      <h3>学习工件 #{{ id }}</h3>
      <p>{{ employeeName || "—" }} · 可溯源、可审批、可回滚</p>
    </div>
    <button class="icon-btn" type="button" title="关闭" @click="drawer.close()">
      <AppIcon name="close" />
    </button>
  </div>

  <div v-if="!detail" class="muted" style="padding: 24px 0">加载中…</div>

  <template v-else>
    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>目标层</span><b class="mono">{{ detail.target_layer }}</b></div>
      <div class="meta"><span>归因</span><b>{{ detail.attribution || "—" }}</b></div>
      <div class="meta"><span>风险</span><b><StatusPill :status="detail.risk" /></b></div>
      <div class="meta"><span>作用域</span><b class="mono">{{ detail.scope }}</b></div>
      <div class="meta"><span>版本</span><b class="mono">v{{ detail.version }}</b></div>
      <div class="meta"><span>创建时间</span><b>{{ fmtDate(detail.created_at) }}</b></div>
      <div class="meta"><span>审批时间</span><b>{{ fmtDate(detail.approved_at) }}</b></div>
    </div>

    <div class="split" style="margin: 16px 0">
      <button
        v-if="['draft', 'pending_approval'].includes(detail.status)"
        class="btn btn-primary"
        @click="approve"
      >
        通过
      </button>
      <button
        v-if="['draft', 'pending_approval'].includes(detail.status)"
        class="btn btn-danger"
        @click="reject"
      >
        驳回
      </button>
      <button v-if="detail.status === 'approved'" class="btn btn-primary" @click="act('activate')">
        直接全量生效
      </button>
      <button v-if="detail.status === 'approved'" class="btn btn-ghost" @click="rollout('shadow')">
        影子观察
      </button>
      <button v-if="detail.status === 'approved'" class="btn btn-ghost" @click="rollout('canary')">
        金丝雀发布
      </button>
      <button v-if="detail.status === 'shadow'" class="btn btn-primary" @click="promote">
        推进到金丝雀
      </button>
      <button v-if="detail.status === 'canary'" class="btn btn-primary" @click="promote">
        推进到全量
      </button>
      <button v-if="['approved', 'active'].includes(detail.status)" class="btn btn-ghost" @click="share('team')">
        共享到团队
      </button>
      <button
        v-if="['approved', 'active'].includes(detail.status)"
        class="btn btn-ghost"
        @click="share('organization')"
      >
        共享到组织
      </button>
      <button
        v-if="['approved', 'active'].includes(detail.status)"
        class="btn btn-ghost"
        @click="rollback"
      >
        回滚
      </button>
      <button
        v-if="detail.status !== 'archived'"
        class="btn btn-ghost"
        @click="createVersion"
      >
        新建版本
      </button>
      <button
        v-if="!['archived', 'rolled_back'].includes(detail.status)"
        class="btn btn-ghost"
        @click="act('archive')"
      >
        归档
      </button>
    </div>

    <div class="section-label">版本谱系</div>
    <div v-if="lineage.length" class="table-wrap">
      <table>
        <thead><tr><th>版本</th><th>状态</th><th>归因</th><th>目标层</th><th>创建时间</th></tr></thead>
        <tbody>
          <tr v-for="item in lineage" :key="item.id">
            <td class="mono">
              v{{ item.version }}
              <span v-if="item.id === detail.id" class="tag">当前</span>
            </td>
            <td><StatusPill :status="item.status" /></td>
            <td>{{ item.attribution || "—" }}</td>
            <td class="mono">{{ item.target_layer }}</td>
            <td class="muted">{{ fmtDate(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="muted" style="font-size: 12px">暂无版本记录。</div>

    <div v-if="detail.rollout?.approval_note || detail.rollout?.reject_reason" class="alert-banner" style="margin-bottom: 16px">
      <div>
        <b>审批意见</b> ·
        {{ detail.rollout?.approval_note || detail.rollout?.reject_reason }}
      </div>
    </div>

    <div v-if="detail.rollout?.mode" class="alert-banner" style="margin-bottom: 16px">
      <div>
        <b>发布状态</b> · {{ detail.rollout.mode }}
        · 流量 {{ detail.rollout.traffic }}
        · 起始 {{ fmtDate(detail.rollout.started_at) }}
      </div>
    </div>

    <div class="section-label">建议方案 · PROPOSAL</div>
    <JsonBlock :value="detail.proposal" />

    <div class="section-label">证据链 · EVIDENCE</div>
    <div v-if="detail.evidence?.length" class="split">
      <span v-for="(item, index) in detail.evidence" :key="index" class="tag">{{ item }}</span>
    </div>
    <div v-else class="muted" style="font-size: 12px">无</div>

    <div class="section-label">评估结果 · EVAL</div>
    <JsonBlock :value="detail.eval_result" />

    <div class="section-label">来源 · SOURCE</div>
    <JsonBlock :value="detail.source" />

    <div class="section-label">发布/回滚记录 · ROLLOUT</div>
    <JsonBlock :value="detail.rollout" />
  </template>
</template>
