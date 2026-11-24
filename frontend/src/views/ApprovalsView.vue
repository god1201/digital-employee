<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import ApprovalDetailDrawer from "@/components/ApprovalDetailDrawer.vue";
import ApprovalFlowEditor from "@/components/ApprovalFlowEditor.vue";
import ApprovalFormEditor from "@/components/ApprovalFormEditor.vue";
import ApprovalNotificationsDrawer from "@/components/ApprovalNotificationsDrawer.vue";
import ApprovalStartModal from "@/components/ApprovalStartModal.vue";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatCard from "@/components/StatCard.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useAuthStore } from "@/stores/auth";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import {
  approvalCategoryLabel,
  approvalModeLabel,
} from "@/utils/approval";
import { esc, fmtDate } from "@/utils/format";

const tab = ref<"inbox" | "mine" | "flows" | "forms" | "stats">("inbox");
const stats = ref<any>({});
const flows = ref<any[]>([]);
const forms = ref<any[]>([]);
const users = ref<any[]>([]);
const employees = ref<any[]>([]);
const tasks = ref<any[]>([]);
const instances = ref<any[]>([]);
const auth = useAuthStore();
const modal = useModalStore();
const drawer = useDrawerStore();
const toast = useToastStore();

const totals = computed(() => stats.value.my_by_status || {});
const unread = computed(() => Number(stats.value.unread_notifications || 0));

async function loadBase(): Promise<void> {
  try {
    const [statsData, flowData, formData, userData, employeeData] = await Promise.all([
      api.get<any>("/approvals/stats"),
      api.get<Paged<any>>("/approvals/flows?page_size=100"),
      api.get<Paged<any>>("/approvals/forms?page_size=100"),
      api.get<any[]>("/approvals/users"),
      api.get<Paged<any>>("/digital-employees?page_size=200").catch(() => ({ items: [] })),
    ]);
    stats.value = statsData;
    flows.value = flowData.items;
    forms.value = formData.items;
    users.value = userData || [];
    employees.value = employeeData.items || [];
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function loadTab(): Promise<void> {
  try {
    if (tab.value === "inbox") {
      tasks.value = (await api.get<Paged<any>>("/approvals/tasks?status=pending&page_size=100")).items;
    } else if (tab.value === "mine") {
      instances.value = (await api.get<Paged<any>>("/approvals/instances?scope=mine&page_size=100")).items;
    }
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

async function refresh(): Promise<void> {
  await loadBase();
  await loadTab();
}

async function changeTab(next: typeof tab.value): Promise<void> {
  tab.value = next;
  await loadTab();
}

function openDetail(id: number): void {
  drawer.open(ApprovalDetailDrawer, { id, onChanged: refresh });
}

function startApproval(flowId: number | null = null): void {
  if (!flows.value.some((flow) => flow.enabled)) {
    toast.push("没有可用审批流程，请先创建或启用流程", "error");
    changeTab("flows");
    return;
  }
  modal.openCustom(ApprovalStartModal, {
    flows: flows.value,
    forms: forms.value,
    users: users.value,
    employees: employees.value,
    selectedFlowId: flowId,
    onCreated: async () => {
      await changeTab("mine");
      await loadBase();
    },
  });
}

function createFlow(): void {
  modal.openCustom(ApprovalFlowEditor, {
    forms: forms.value,
    users: users.value,
    onSaved: refresh,
  });
}

function editFlow(flow: any): void {
  modal.openCustom(ApprovalFlowEditor, {
    flow,
    forms: forms.value,
    users: users.value,
    onSaved: refresh,
  });
}

async function removeFlow(flow: any): Promise<void> {
  if (!confirm("确认删除该审批流程？已有实例时将被拒绝。")) return;
  try {
    await api.delete(`/approvals/flows/${flow.id}`);
    toast.push("流程已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

function createForm(): void {
  modal.openCustom(ApprovalFormEditor, { onSaved: refresh });
}

function editForm(form: any): void {
  modal.openCustom(ApprovalFormEditor, { form, onSaved: refresh });
}

async function removeForm(form: any): Promise<void> {
  if (!confirm("确认删除该审批表单？已被流程引用时将被拒绝。")) return;
  try {
    await api.delete(`/approvals/forms/${form.id}`);
    toast.push("表单已删除");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "删除失败", "error");
  }
}

function openNotifications(): void {
  drawer.open(ApprovalNotificationsDrawer, { onChanged: loadBase });
}

function decide(taskId: number, decision: "approve" | "reject"): void {
  modal.openForm({
    title: decision === "approve" ? "通过审批" : "驳回审批",
    sub: `审批任务 #${taskId}`,
    fields: [
      { name: "comment", label: decision === "approve" ? "审批意见" : "驳回原因", type: "textarea", rows: 3 },
    ],
    submitLabel: decision === "approve" ? "确认通过" : "确认驳回",
    onSubmit: async (values) => {
      await api.post(`/approvals/tasks/${taskId}/${decision}`, { comment: values.comment || "" });
      toast.push(decision === "approve" ? "已通过" : "已驳回");
      await refresh();
    },
  });
}

function transfer(taskId: number): void {
  const options = users.value
    .filter((user) => user.id !== auth.user?.id)
    .map((user) => ({ value: user.id, label: `${user.full_name || user.username} · ${user.username}` }));
  modal.openForm({
    title: "转办审批",
    sub: `审批任务 #${taskId}`,
    fields: [
      { name: "target_user_id", label: "转办给", type: "select", options, required: true },
      { name: "comment", label: "转办说明", type: "textarea", rows: 3 },
    ],
    submitLabel: "确认转办",
    onSubmit: async (values) => {
      await api.post(`/approvals/tasks/${taskId}/transfer`, {
        target_user_id: Number(values.target_user_id),
        comment: values.comment || "",
      });
      toast.push("已转办");
      await refresh();
    },
  });
}

function addSign(taskId: number): void {
  modal.openForm({
    title: "加签审批人",
    sub: `审批任务 #${taskId}`,
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
      await api.post(`/approvals/tasks/${taskId}/add-sign`, {
        user_ids: (values.user_ids || []).map(Number),
        comment: values.comment || "",
      });
      toast.push("已加签");
      await refresh();
    },
  });
}

async function cancelInstance(instance: any): Promise<void> {
  if (!confirm("确认取消该审批？")) return;
  try {
    await api.post(`/approvals/instances/${instance.id}/cancel`, { comment: "" });
    toast.push("审批已取消");
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "取消失败", "error");
  }
}

async function remindInstance(instance: any): Promise<void> {
  try {
    const result = await api.post<any>(`/approvals/instances/${instance.id}/remind`, { comment: "" });
    toast.push(`已催办 ${result.notified || 0} 位审批人`);
    await refresh();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "催办失败", "error");
  }
}

const statusRows = computed(() =>
  Object.entries(totals.value).map(([status, count]) => ({ status, count })),
);
const categoryRows = computed(() =>
  Object.entries(stats.value.my_by_category || {}).map(([category, count]) => ({ category, count })),
);

onMounted(async () => {
  await loadBase();
  await loadTab();
});
</script>

<template>
  <PageHeader
    eyebrow="business / approval"
    title="审批流"
    sub="通用表单、条件分支、会签 / 或签 / 依次审批、转办、加签、超时处理与数字员工任务联动。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="openNotifications">
        <AppIcon name="bell" />通知{{ unread ? ` (${unread})` : "" }}
      </button>
      <button v-if="tab === 'flows'" class="btn btn-primary" @click="createFlow">
        <AppIcon name="plus" />新建流程
      </button>
      <button v-else-if="tab === 'forms'" class="btn btn-primary" @click="createForm">
        <AppIcon name="plus" />新建表单
      </button>
      <button v-else class="btn btn-primary" @click="startApproval()">
        <AppIcon name="plus" />发起审批
      </button>
    </template>
  </PageHeader>

  <div class="aigc-stats-grid">
    <StatCard label="待我审批" :value="stats.pending_for_me ?? 0" :meta="`超时 ${stats.overdue_for_me ?? 0} · 未读通知 ${unread}`" :index="0" />
    <StatCard label="我发起的" :value="stats.my_total ?? 0" :meta="`进行中 ${totals.running ?? 0}`" tone="var(--blue)" :index="1" />
    <StatCard label="已通过" :value="totals.approved ?? 0" :meta="`平均耗时 ${Number(stats.my_avg_duration_hours || 0).toFixed(1)}h`" tone="var(--mint)" :index="2" />
    <StatCard label="已驳回" :value="totals.rejected ?? 0" :meta="`取消 ${totals.cancelled ?? 0}`" tone="var(--coral)" :index="3" />
  </div>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'inbox' }" @click="changeTab('inbox')">
      待我审批 <span class="dim">{{ stats.pending_for_me ?? 0 }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'mine' }" @click="changeTab('mine')">
      我发起的 <span class="dim">{{ stats.my_total ?? 0 }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'flows' }" @click="changeTab('flows')">
      流程模板 <span class="dim">{{ flows.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'forms' }" @click="changeTab('forms')">
      表单模板 <span class="dim">{{ forms.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'stats' }" @click="changeTab('stats')">统计</button>
  </div>

  <div v-if="tab === 'inbox'" class="panel">
    <DataTable
      :rows="tasks"
      :columns="[
        { label: '审批事项', format: (row) => `<div class='cell-main'><b>${esc(row.instance_title || '—')}</b><small>${esc(row.flow_name || '')} · ${esc(row.node_name)}</small></div>` },
        { label: '发起人', format: (row) => esc(row.initiator_name || '—') },
        { label: '会签模式', format: (row) => `<span class='tag'>${esc(approvalModeLabel(row.mode))}</span>` },
        { label: '到期', format: (row) => row.due_at ? `<span class='mono'>${fmtDate(row.due_at)}</span>` : '<span class=\'dim\'>—</span>' },
        { label: '状态', key: 'status' },
        { label: '', key: 'actions' },
      ]"
      empty-text="没有待你审批的事项。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="decide(row.id, 'approve')">通过</button>
          <button class="btn btn-sm btn-danger" @click="decide(row.id, 'reject')">驳回</button>
          <button class="btn btn-sm btn-ghost" @click="transfer(row.id)">转办</button>
          <button class="btn btn-sm btn-ghost" @click="addSign(row.id)">加签</button>
          <button class="btn btn-sm btn-ghost" @click="openDetail(row.instance_id)">详情</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else-if="tab === 'mine'" class="panel">
    <DataTable
      :rows="instances"
      :columns="[
        { label: '审批事项', format: (row) => `<div class='cell-main'><b>${esc(row.title)}</b><small>${esc(row.flow_name || '—')}</small></div>` },
        { label: '分类', format: (row) => `<span class='tag'>${esc(approvalCategoryLabel(row.category))}</span>` },
        { label: '状态', key: 'status' },
        { label: '当前节点', format: (row) => `<span class='muted'>${esc(row.current_node_name || '—')}</span>` },
        { label: '进度', format: (row) => `<span class='mono'>${row.progress?.completed ?? 0}/${row.progress?.total ?? 0}</span>` },
        { label: '创建', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="你还没有发起过审批。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openDetail(row.id)">详情</button>
          <button v-if="row.status === 'running'" class="btn btn-sm btn-ghost" @click="remindInstance(row)">催办</button>
          <button v-if="row.status === 'running'" class="btn btn-sm btn-danger" @click="cancelInstance(row)">取消</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else-if="tab === 'flows'" class="panel">
    <DataTable
      :rows="flows"
      :columns="[
        { label: '流程', format: (row) => `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>` },
        { label: '分类', format: (row) => `<span class='tag'>${esc(approvalCategoryLabel(row.category))}</span>` },
        { label: '表单', format: (row) => esc(row.form_name || '—') },
        { label: '节点', format: (row) => `<span class='mono'>${row.node_count}</span>` },
        { label: '状态', key: 'status' },
        { label: '更新', format: (row) => `<span class='muted'>${fmtDate(row.updated_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有审批流程。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.enabled ? 'active' : 'disabled'" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button v-if="row.enabled" class="btn btn-sm" @click="startApproval(row.id)">发起</button>
          <button class="btn btn-sm btn-ghost" @click="editFlow(row)">编辑</button>
          <button class="btn btn-sm btn-danger" @click="removeFlow(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else-if="tab === 'forms'" class="panel">
    <DataTable
      :rows="forms"
      :columns="[
        { label: '表单', format: (row) => `<div class='cell-main'><b>${esc(row.name)}</b><small class='mono'>${esc(row.code)}</small></div>` },
        { label: '分类', format: (row) => `<span class='tag'>${esc(approvalCategoryLabel(row.category))}</span>` },
        { label: '字段', format: (row) => `<span class='mono'>${row.field_count}</span>` },
        { label: '状态', key: 'status' },
        { label: '更新', format: (row) => `<span class='muted'>${fmtDate(row.updated_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有审批表单。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.enabled ? 'active' : 'disabled'" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-ghost" @click="editForm(row)">编辑</button>
          <button class="btn btn-sm btn-danger" @click="removeForm(row)">删除</button>
        </div>
      </template>
    </DataTable>
  </div>

  <div v-else>
    <div class="panel" style="margin-bottom: 16px">
      <div class="panel-head"><div><div class="panel-title">我发起的审批 · 状态分布</div><div class="panel-sub">按流程状态统计</div></div></div>
      <DataTable
        :rows="statusRows"
        :columns="[
          { label: '状态', key: 'status' },
          { label: '数量', format: (row) => `<span class='mono'>${row.count}</span>` },
        ]"
        empty-text="暂无数据"
      >
        <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      </DataTable>
    </div>
    <div class="panel" style="margin-bottom: 16px">
      <div class="panel-head"><div><div class="panel-title">按业务分类</div><div class="panel-sub">财务 / 合同 / 文书 / 自定义</div></div></div>
      <DataTable
        :rows="categoryRows"
        :columns="[
          { label: '分类', format: (row) => `<span class='tag'>${esc(approvalCategoryLabel(row.category))}</span>` },
          { label: '数量', format: (row) => `<span class='mono'>${row.count}</span>` },
        ]"
        empty-text="暂无数据"
      />
    </div>
    <div class="panel">
      <div class="panel-head"><div><div class="panel-title">审批效率</div><div class="panel-sub">已通过实例的平均耗时</div></div></div>
      <div class="meta-grid">
        <div class="meta"><span>待我审批</span><b>{{ stats.pending_for_me ?? 0 }}</b></div>
        <div class="meta"><span>超时未处理</span><b>{{ stats.overdue_for_me ?? 0 }}</b></div>
        <div class="meta"><span>我发起总数</span><b>{{ stats.my_total ?? 0 }}</b></div>
        <div class="meta"><span>平均耗时</span><b>{{ Number(stats.my_avg_duration_hours || 0).toFixed(2) }} 小时</b></div>
      </div>
    </div>
  </div>
</template>
