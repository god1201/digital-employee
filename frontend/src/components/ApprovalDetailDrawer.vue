<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useAuthStore } from "@/stores/auth";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import {
  approvalActionLabel,
  approvalCategoryLabel,
  approvalFormatFieldValue,
  approvalModeLabel,
  approvalNodeTypeLabel,
  approvalUserLabel,
} from "@/utils/approval";
import { fmtDate } from "@/utils/format";

const props = defineProps<{ id: number; onChanged?: () => void }>();
const auth = useAuthStore();
const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();
const detail = ref<any>(null);
const users = ref<any[]>([]);
const employees = ref<any[]>([]);

const myTask = computed(() => (detail.value?.my_tasks || [])[0]);
const canManage = computed(
  () =>
    detail.value?.initiator_id === auth.user?.id || Boolean(auth.user?.is_superuser),
);

const steps = computed(() => {
  const nodes = detail.value?.flow_snapshot?.nodes || [];
  const states = detail.value?.node_states || {};
  return nodes.map((node: any, index: number) => {
    const state = states[node.key] || {};
    const status = state.status || "pending";
    const cls =
      status === "rejected"
        ? "rejected"
        : ["approved", "skipped"].includes(status)
          ? "done"
          : detail.value?.current_node_key === node.key
            ? "current"
            : "";
    const dot = status === "approved" ? "✓" : status === "rejected" ? "×" : status === "skipped" ? "↷" : String(index + 1);
    const sub = [
      approvalNodeTypeLabel(node.type),
      node.type === "approval" ? approvalModeLabel(node.mode) : "",
      state.target ? `跳转 → ${state.target}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return { ...node, state, status, cls, dot, sub };
  });
});

async function load(): Promise<void> {
  try {
    const [detailData, userData, employeeData] = await Promise.all([
      api.get(`/approvals/instances/${props.id}`),
      api.get<any[]>("/approvals/users"),
      api.get<Paged<any>>("/digital-employees?page_size=200").catch(() => ({ items: [] })),
    ]);
    detail.value = detailData;
    users.value = userData || [];
    employees.value = employeeData.items || [];
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function afterAction(): Promise<void> {
  await load();
  props.onChanged?.();
}

function decide(decision: "approve" | "reject"): void {
  if (!myTask.value) return;
  modal.openForm({
    title: decision === "approve" ? "通过审批" : "驳回审批",
    sub: `审批任务 #${myTask.value.id}`,
    fields: [
      {
        name: "comment",
        label: decision === "approve" ? "审批意见" : "驳回原因",
        type: "textarea",
        rows: 3,
      },
    ],
    submitLabel: decision === "approve" ? "确认通过" : "确认驳回",
    onSubmit: async (values) => {
      await api.post(`/approvals/tasks/${myTask.value.id}/${decision}`, {
        comment: values.comment || "",
      });
      toast.push(decision === "approve" ? "已通过" : "已驳回");
      await afterAction();
    },
  });
}

function transfer(): void {
  if (!myTask.value) return;
  const options = users.value
    .filter((user) => user.id !== auth.user?.id)
    .map((user) => ({ value: user.id, label: `${user.full_name || user.username} · ${user.username}` }));
  modal.openForm({
    title: "转办审批",
    sub: `审批任务 #${myTask.value.id}`,
    fields: [
      { name: "target_user_id", label: "转办给", type: "select", options, required: true },
      { name: "comment", label: "转办说明", type: "textarea", rows: 3 },
    ],
    submitLabel: "确认转办",
    onSubmit: async (values) => {
      await api.post(`/approvals/tasks/${myTask.value.id}/transfer`, {
        target_user_id: Number(values.target_user_id),
        comment: values.comment || "",
      });
      toast.push("已转办");
      await afterAction();
    },
  });
}

function addSign(): void {
  if (!myTask.value) return;
  modal.openForm({
    title: "加签审批人",
    sub: `审批任务 #${myTask.value.id}`,
    fields: [
      {
        name: "user_ids",
        label: "加签用户",
        type: "multiselect",
        required: true,
        numeric: true,
        size: 6,
        options: users.value.map((user) => ({
          value: user.id,
          label: `${user.full_name || user.username} · ${user.username}`,
        })),
      },
      { name: "comment", label: "加签说明", type: "textarea", rows: 3 },
    ],
    submitLabel: "确认加签",
    onSubmit: async (values) => {
      await api.post(`/approvals/tasks/${myTask.value.id}/add-sign`, {
        user_ids: (values.user_ids || []).map(Number),
        comment: values.comment || "",
      });
      toast.push("已加签");
      await afterAction();
    },
  });
}

async function cancel(): Promise<void> {
  if (!confirm("确认取消该审批？")) return;
  try {
    await api.post(`/approvals/instances/${props.id}/cancel`, { comment: "" });
    toast.push("审批已取消");
    await afterAction();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "取消失败", "error");
  }
}

async function remind(): Promise<void> {
  try {
    const result = await api.post<any>(`/approvals/instances/${props.id}/remind`, { comment: "" });
    toast.push(`已催办 ${result.notified || 0} 位审批人`);
    await afterAction();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "催办失败", "error");
  }
}

function launchTask(): void {
  modal.openForm({
    title: "创建数字员工任务",
    sub: "审批已通过，可把表单内容交给数字员工继续处理。",
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        value: detail.value?.employee_id || "",
        options: employees.value.map((employee) => ({
          value: employee.id,
          label: `${employee.name} · ${employee.code}`,
        })),
      },
    ],
    submitLabel: "创建任务",
    onSubmit: async (values) => {
      const result = await api.post<any>(`/approvals/instances/${props.id}/launch-task`, {
        employee_id: Number(values.employee_id),
      });
      toast.push(`已创建任务 #${result.task_instance_id}`);
      await afterAction();
    },
  });
}

onMounted(load);
</script>

<template>
  <div v-if="detail">
    <div class="drawer-head">
      <div>
        <h3>{{ detail.title }}</h3>
        <p>{{ detail.flow_name || "—" }} · {{ approvalCategoryLabel(detail.category) }}</p>
      </div>
      <button class="icon-btn" @click="drawer.close()"><AppIcon name="close" /></button>
    </div>

    <div class="meta-grid">
      <div class="meta"><span>状态</span><b><StatusPill :status="detail.status" /></b></div>
      <div class="meta"><span>发起人</span><b>{{ detail.initiator_name || approvalUserLabel(users, detail.initiator_id) }}</b></div>
      <div class="meta"><span>当前节点</span><b>{{ detail.current_node_name || "—" }}</b></div>
      <div class="meta"><span>进度</span><b>{{ detail.progress?.completed ?? 0 }} / {{ detail.progress?.total ?? 0 }}</b></div>
      <div class="meta"><span>创建</span><b>{{ fmtDate(detail.created_at) }}</b></div>
      <div class="meta"><span>完成</span><b>{{ detail.completed_at ? fmtDate(detail.completed_at) : "—" }}</b></div>
      <div class="meta"><span>业务编号</span><b>{{ detail.business_ref || "—" }}</b></div>
      <div class="meta"><span>关联任务</span><b>{{ detail.task_instance_id ? `#${detail.task_instance_id}` : "—" }}</b></div>
    </div>

    <div v-if="detail.error" class="alert-banner"><div>{{ detail.error }}</div></div>

    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px">
      <template v-if="myTask">
        <button class="btn btn-sm" @click="decide('approve')">通过</button>
        <button class="btn btn-sm btn-danger" @click="decide('reject')">驳回</button>
        <button class="btn btn-sm btn-ghost" @click="transfer">转办</button>
        <button class="btn btn-sm btn-ghost" @click="addSign">加签</button>
      </template>
      <button v-if="detail.status === 'running' && canManage" class="btn btn-sm btn-ghost" @click="remind">催办</button>
      <button v-if="detail.status === 'running' && canManage" class="btn btn-sm btn-danger" @click="cancel">取消</button>
      <button
        v-if="detail.status === 'approved' && !detail.task_instance_id && canManage"
        class="btn btn-sm"
        @click="launchTask"
      >
        创建员工任务
      </button>
    </div>

    <div class="section-label">FLOW PROGRESS</div>
    <div class="approval-steps">
      <div v-for="step in steps" :key="step.key" class="approval-step" :class="step.cls">
        <div class="dot">{{ step.dot }}</div>
        <div>
          <div class="name">{{ step.name }}</div>
          <div class="sub">{{ step.sub || "等待中" }}</div>
        </div>
        <span class="dim mono" style="font-size: 10px">{{ step.key }}</span>
      </div>
    </div>

    <div class="section-label">FORM DATA</div>
    <div v-if="detail.form_snapshot?.fields?.length" class="table-wrap">
      <table>
        <thead><tr><th>字段</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="field in detail.form_snapshot.fields" :key="field.name">
            <td>{{ field.label }}</td>
            <td style="white-space: pre-wrap">
              {{ approvalFormatFieldValue(field, detail.form_data?.[field.name], users) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <JsonBlock v-else :value="detail.form_data || {}" />

    <div class="section-label">APPROVAL TASKS</div>
    <div v-if="detail.tasks?.length" class="table-wrap">
      <table>
        <thead><tr><th>审批人</th><th>节点</th><th>模式</th><th>状态</th><th>意见</th><th>处理时间</th></tr></thead>
        <tbody>
          <tr v-for="task in detail.tasks" :key="task.id">
            <td>{{ approvalUserLabel(users, task.approver_id) }}</td>
            <td>{{ task.node_name }}</td>
            <td><span class="tag">{{ approvalModeLabel(task.mode) }}</span></td>
            <td>
              <StatusPill :status="task.status" />
              <span v-if="task.is_added" class="tag">加签</span>
              <small v-if="task.delegated_from" class="dim"> 来自 #{{ task.delegated_from }}</small>
            </td>
            <td class="muted">{{ task.comment || "—" }}</td>
            <td class="muted">{{ task.acted_at ? fmtDate(task.acted_at) : "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">还没有审批人任务</div>

    <div class="section-label">TIMELINE</div>
    <div v-if="detail.actions?.length" class="table-wrap">
      <table>
        <thead><tr><th>动作</th><th>节点</th><th>操作人</th><th>对象</th><th>说明</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="action in detail.actions" :key="action.id">
            <td><span class="tag">{{ approvalActionLabel(action.action) }}</span></td>
            <td class="mono dim">{{ action.node_key || "—" }}</td>
            <td>{{ action.actor_id ? approvalUserLabel(users, action.actor_id) : "系统" }}</td>
            <td>{{ action.target_user_id ? approvalUserLabel(users, action.target_user_id) : "—" }}</td>
            <td class="muted">{{ action.comment || "—" }}</td>
            <td class="muted">{{ fmtDate(action.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">还没有时间线记录</div>
  </div>
</template>
