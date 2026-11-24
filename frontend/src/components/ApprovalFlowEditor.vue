<script setup lang="ts">
import { ref } from "vue";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { approvalModeLabel, approvalNodeTypeLabel } from "@/utils/approval";

const props = defineProps<{
  flow?: any | null;
  forms: any[];
  users: any[];
  onSaved?: () => void;
}>();

const modal = useModalStore();
const toast = useToastStore();

const name = ref(props.flow?.name || "");
const code = ref(props.flow?.code || "");
const category = ref(props.flow?.category || "custom");
const formId = ref<number | "">(props.flow?.form_id ?? "");
const description = ref(props.flow?.description || "");
const enabled = ref(String(props.flow?.enabled ?? true));
const error = ref("");
const submitting = ref(false);

function nodeDefault(type: string, key: string): any {
  if (type === "condition") {
    return { key, name: "条件判断", type, field: "amount", operator: "gt", value: "", on_true: "", on_false: "" };
  }
  if (type === "cc") return { key, name: "抄送通知", type, cc: [] };
  if (type === "end") return { key, name: "结束", type };
  return {
    key,
    name: "审批节点",
    type: "approval",
    approvers: [],
    mode: "any",
    timeout_hours: 24,
    timeout_action: "remind",
    escalate_to: [],
    cc: [],
    allow_transfer: true,
    allow_add_sign: true,
  };
}

const nodes = ref<any[]>(
  props.flow?.nodes?.length
    ? JSON.parse(JSON.stringify(props.flow.nodes))
    : [nodeDefault("approval", "n1"), nodeDefault("end", "end")],
);

function newKey(): string {
  const keys = new Set(nodes.value.map((node) => node.key));
  let index = nodes.value.length + 1;
  while (keys.has(`n${index}`)) index += 1;
  return `n${index}`;
}

function addNode(): void {
  nodes.value.push(nodeDefault("approval", newKey()));
}

function removeNode(index: number): void {
  nodes.value.splice(index, 1);
}

function moveNode(index: number, offset: number): void {
  const target = index + offset;
  if (target < 0 || target >= nodes.value.length) return;
  [nodes.value[index], nodes.value[target]] = [nodes.value[target], nodes.value[index]];
}

function changeType(index: number, event: Event): void {
  const type = (event.target as HTMLSelectElement).value;
  const current = nodes.value[index];
  nodes.value[index] = { ...nodeDefault(type, current.key), name: current.name || approvalNodeTypeLabel(type) };
}

function approverOptions(): Array<{ value: any; label: string }> {
  return [
    { value: "admin", label: "全部管理员" },
    { value: "initiator", label: "发起人" },
    ...props.users.map((user) => ({
      value: user.id,
      label: `${user.full_name || user.username} · ${user.username}`,
    })),
  ];
}

function targetOptions(currentKey: string): Array<{ value: string; label: string }> {
  return [
    { value: "", label: "默认下一个节点" },
    ...nodes.value
      .filter((node) => node.key !== currentKey)
      .map((node) => ({ value: node.key, label: `${node.name} · ${node.key}` })),
  ];
}

function buildNodes(): any[] {
  return nodes.value.map((node) => {
    const item: any = {
      key: node.key,
      name: String(node.name || "").trim() || approvalNodeTypeLabel(node.type),
      type: node.type,
    };
    if (node.type === "approval") {
      if (!node.approvers?.length) throw new Error(`审批节点「${item.name}」至少选择一个审批人`);
      item.approvers = [...node.approvers];
      item.mode = node.mode;
      item.timeout_hours = Number(node.timeout_hours) || 0;
      item.timeout_action = node.timeout_action;
      item.escalate_to = [...(node.escalate_to || [])];
      item.cc = [...(node.cc || [])];
      item.allow_transfer = Boolean(node.allow_transfer);
      item.allow_add_sign = Boolean(node.allow_add_sign);
    } else if (node.type === "condition") {
      if (!String(node.field || "").trim()) throw new Error(`条件节点「${item.name}」缺少判断字段`);
      item.field = node.field;
      item.operator = node.operator;
      item.value =
        ["in", "not_in"].includes(node.operator) && typeof node.value === "string"
          ? node.value.split(/[,，\n]/).map((value: string) => value.trim()).filter(Boolean)
          : node.value;
      item.on_true = node.on_true || null;
      item.on_false = node.on_false || null;
    } else if (node.type === "cc") {
      if (!node.cc?.length) throw new Error(`抄送节点「${item.name}」至少选择一个抄送人`);
      item.cc = [...node.cc];
    }
    return item;
  });
}

async function submit(): Promise<void> {
  error.value = "";
  submitting.value = true;
  try {
    const body = {
      name: name.value.trim(),
      code: code.value.trim(),
      category: category.value,
      form_id: formId.value ? Number(formId.value) : null,
      description: description.value,
      enabled: enabled.value === "true",
      nodes: buildNodes(),
      config: props.flow?.config || {},
    };
    if (!body.name || !body.code) throw new Error("请填写流程名称和编码");
    if (props.flow) await api.patch(`/approvals/flows/${props.flow.id}`, body);
    else await api.post("/approvals/flows", body);
    toast.push("审批流程已保存");
    modal.close();
    props.onSaved?.();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal" style="width: min(1120px, 96vw)">
    <div class="modal-head">
      <div>
        <h3>{{ flow ? "编辑审批流程" : "新建审批流程" }}</h3>
        <p>节点按顺序执行；条件节点可跳转到任意节点 key。</p>
      </div>
      <button class="icon-btn" type="button" @click="modal.close()"><AppIcon name="close" /></button>
    </div>
    <form autocomplete="off" @submit.prevent="submit">
      <div class="modal-body">
        <div class="form-grid">
          <div class="field"><label>流程名称</label><input v-model="name" required /></div>
          <div class="field"><label>流程编码</label><input v-model="code" required /></div>
          <div class="field">
            <label>业务分类</label>
            <select v-model="category">
              <option value="finance">财务</option>
              <option value="contract">合同</option>
              <option value="document">文书</option>
              <option value="custom">自定义</option>
            </select>
          </div>
          <div class="field">
            <label>绑定表单</label>
            <select v-model="formId">
              <option value="">不绑定表单</option>
              <option v-for="form in forms" :key="form.id" :value="form.id">
                {{ form.name }} · {{ form.category }}{{ form.enabled ? "" : "（停用）" }}
              </option>
            </select>
          </div>
          <div class="field full"><label>流程说明</label><textarea v-model="description" rows="2" /></div>
          <div class="field">
            <label>状态</label>
            <select v-model="enabled">
              <option value="true">启用</option>
              <option value="false">停用</option>
            </select>
          </div>
        </div>

        <div class="section-label">节点编排</div>
        <div
          v-for="(node, index) in nodes"
          :key="node.key"
          class="approval-node-row"
        >
          <div class="node-row-head">
            <span class="node-index">{{ index + 1 }}</span>
            <select :value="node.type" @change="changeType(index, $event)">
              <option value="approval">审批</option>
              <option value="condition">条件</option>
              <option value="cc">抄送</option>
              <option value="end">结束</option>
            </select>
            <input v-model="node.name" placeholder="节点名称" />
            <div class="node-actions">
              <button type="button" class="icon-btn" :disabled="index === 0" @click="moveNode(index, -1)">↑</button>
              <button type="button" class="icon-btn" :disabled="index === nodes.length - 1" @click="moveNode(index, 1)">↓</button>
              <button type="button" class="icon-btn" @click="removeNode(index)"><AppIcon name="close" /></button>
            </div>
          </div>

          <div v-if="node.type === 'approval'" class="node-config">
            <div class="field full">
              <label>审批人</label>
              <select v-model="node.approvers" multiple size="4">
                <option v-for="option in approverOptions()" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
              <span class="help">支持多选，可选“全部管理员”或“发起人”。</span>
            </div>
            <div class="field">
              <label>会签模式</label>
              <select v-model="node.mode">
                <option value="any">或签（任一通过）</option>
                <option value="all">会签（全部通过）</option>
                <option value="sequence">依次审批</option>
              </select>
            </div>
            <div class="field">
              <label>超时小时（0 不超时）</label>
              <input v-model.number="node.timeout_hours" type="number" min="0" max="720" />
            </div>
            <div class="field">
              <label>超时动作</label>
              <select v-model="node.timeout_action">
                <option value="remind">提醒</option>
                <option value="auto_approve">自动通过</option>
                <option value="auto_reject">自动驳回</option>
                <option value="escalate">升级转办</option>
              </select>
            </div>
            <div class="field full">
              <label>升级审批人（超时升级时）</label>
              <select v-model="node.escalate_to" multiple size="3">
                <option v-for="option in approverOptions()" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="field full">
              <label>抄送人（可选）</label>
              <select v-model="node.cc" multiple size="3">
                <option v-for="option in approverOptions()" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>允许转办</label>
              <select v-model="node.allow_transfer">
                <option :value="true">是</option>
                <option :value="false">否</option>
              </select>
            </div>
            <div class="field">
              <label>允许加签</label>
              <select v-model="node.allow_add_sign">
                <option :value="true">是</option>
                <option :value="false">否</option>
              </select>
            </div>
          </div>

          <div v-else-if="node.type === 'condition'" class="node-config">
            <div class="field"><label>判断字段</label><input v-model="node.field" placeholder="例如 amount" /></div>
            <div class="field">
              <label>判断符</label>
              <select v-model="node.operator">
                <option value="eq">等于</option>
                <option value="ne">不等于</option>
                <option value="gt">大于</option>
                <option value="gte">大于等于</option>
                <option value="lt">小于</option>
                <option value="lte">小于等于</option>
                <option value="in">属于</option>
                <option value="not_in">不属于</option>
                <option value="contains">包含</option>
                <option value="exists">存在</option>
              </select>
            </div>
            <div class="field">
              <label>比较值</label>
              <input v-model="node.value" placeholder="数字或文本；in 用逗号分隔" />
            </div>
            <div class="field">
              <label>条件成立跳转</label>
              <select v-model="node.on_true">
                <option v-for="option in targetOptions(node.key)" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>条件不成立跳转</label>
              <select v-model="node.on_false">
                <option v-for="option in targetOptions(node.key)" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
          </div>

          <div v-else-if="node.type === 'cc'" class="node-config">
            <div class="field full">
              <label>抄送人</label>
              <select v-model="node.cc" multiple size="4">
                <option v-for="option in approverOptions()" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
          </div>

          <div v-else class="hint-box">流程在此结束，审批实例状态变为已通过。</div>

          <div class="dim mono" style="font-size: 9.5px; margin-top: 8px">key: {{ node.key }}</div>
        </div>

        <button type="button" class="btn btn-sm" style="margin-top: 8px" @click="addNode">
          <AppIcon name="plus" />添加节点
        </button>
        <div class="hint-box" style="margin-top: 12px">
          提示：条件节点用表单字段判断，例如 amount 大于 5000 跳到“总经理审批”。节点 key 用于条件跳转，创建后不建议修改。
        </div>
        <div class="form-error" :class="{ show: error }">{{ error }}</div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" @click="modal.close()">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="submitting">
          {{ submitting ? "保存中..." : flow ? "保存流程" : "创建流程" }}
        </button>
      </div>
    </form>
  </div>
</template>
