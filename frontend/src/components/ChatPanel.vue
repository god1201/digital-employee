<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { API_BASE, api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import TaskDetailDrawer from "@/components/TaskDetailDrawer.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

const props = withDefaults(
  defineProps<{
    employeeId?: number | null;
    conversationId?: number | null;
    compact?: boolean;
  }>(),
  { employeeId: null, conversationId: null, compact: false },
);
const emit = defineEmits<{ (event: "updated"): void }>();

const toast = useToastStore();
const drawer = useDrawerStore();
const conversation = ref<any>(null);
const members = ref<any[]>([]);
const messages = ref<any[]>([]);
const draft = ref("");
const routingMode = ref<"auto" | "all" | "explicit">("auto");
const explicitTargets = ref<number[]>([]);
const composerMode = ref<"message" | "task">("message");
const taskEmployeeId = ref<number | null>(null);
const attachedDocuments = ref<any[]>([]);
const attachedConversations = ref<any[]>([]);
const attachedFiles = ref<any[]>([]);
const uploading = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const abortController = ref<AbortController | null>(null);
const streamStopped = ref(false);
const documentOptions = ref<any[]>([]);
const conversationOptions = ref<any[]>([]);
const loading = ref(false);
const sending = ref(false);
const error = ref("");
const bodyRef = ref<HTMLElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const mentionOpen = ref(false);
const mentionQuery = ref("");
const mentionStart = ref(-1);
const mentionIndex = ref(0);
const slashIndex = ref(0);
const decidingKey = ref("");

const SLASH_COMMANDS = [
  { name: "任务", desc: "把当前内容创建为任务" },
  { name: "确认", desc: "批准当前所有待确认工具" },
  { name: "总结", desc: "让员工总结当前对话" },
  { name: "重试", desc: "重发上一条消息" },
];

const isGroup = computed(() => conversation.value?.mode === "group");

const memberName = (id: number | null) =>
  members.value.find((item) => item.employee_id === id)?.name || "数字员工";

const targetMembers = computed(() =>
  members.value.filter((member) => explicitTargets.value.includes(member.employee_id)),
);

const slashQuery = computed(() => {
  const match = /^\/(\S*)$/.exec(draft.value);
  return match ? match[1] : null;
});
const slashOpen = computed(
  () => slashQuery.value !== null && !mentionOpen.value,
);
const slashCandidates = computed(() => {
  const text = (slashQuery.value || "").toLowerCase();
  return SLASH_COMMANDS.filter((command) =>
    command.name.toLowerCase().includes(text),
  );
});

const mentionItems = computed(() => {
  const text = mentionQuery.value.trim().toLowerCase();
  const items: any[] = [];
  if (isGroup.value) {
    for (const member of members.value) {
      const haystack = [member.name, member.position, member.agent_name]
        .join(" ")
        .toLowerCase();
      if (text && !haystack.includes(text)) continue;
      items.push({
        type: "employee",
        key: `e-${member.employee_id}`,
        label: member.name,
        sub: member.position || member.agent_name || "数字员工",
        data: member,
      });
    }
  }
  for (const document of documentOptions.value) {
    const haystack = [document.title, document.base_name, document.source]
      .join(" ")
      .toLowerCase();
    if (text && !haystack.includes(text)) continue;
    items.push({
      type: "document",
      key: `d-${document.id}`,
      label: document.title,
      sub: `文件 · ${document.base_name || "知识库"}`,
      data: document,
    });
  }
  for (const item of conversationOptions.value) {
    if (item.id === conversation.value?.id) continue;
    const haystack = [item.title, ...(item.member_names || [])]
      .join(" ")
      .toLowerCase();
    if (text && !haystack.includes(text)) continue;
    items.push({
      type: "conversation",
      key: `c-${item.id}`,
      label: item.title || `会话 #${item.id}`,
      sub: `会话 · ${(item.member_names || []).join("、") || item.mode}`,
      data: item,
    });
  }
  return items;
});

const mentionSections = computed(() => {
  const labels: Record<string, string> = {
    employee: "数字员工",
    document: "文件",
    conversation: "会话",
  };
  return ["employee", "document", "conversation"]
    .map((type) => ({
      type,
      label: labels[type],
      items: mentionItems.value
        .map((item, index) => ({ ...item, index }))
        .filter((item) => item.type === type),
    }))
    .filter((section) => section.items.length);
});

const title = computed(() => {
  if (!conversation.value) return "数字员工对话";
  return conversation.value.title || "数字员工对话";
});

function scrollBottom(): void {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight;
  });
}

function applyDetail(data: any): void {
  conversation.value = data.conversation;
  members.value = data.members || [];
  messages.value = data.messages || [];
  if (!taskEmployeeId.value && members.value.length) {
    taskEmployeeId.value = members.value[0].employee_id;
  }
  scrollBottom();
}

async function loadContextOptions(): Promise<void> {
  try {
    const [documentData, conversationData] = await Promise.all([
      api.get<any>("/knowledge-documents?page_size=100"),
      api.get<any[]>("/conversations?limit=100"),
    ]);
    documentOptions.value = documentData.items || [];
    conversationOptions.value = conversationData || [];
  } catch {
    // @文件/@会话 是增强能力，加载失败不阻塞对话
    documentOptions.value = [];
    conversationOptions.value = [];
  }
}

function clearAttachments(): void {
  attachedDocuments.value = [];
  attachedConversations.value = [];
  attachedFiles.value = [];
}

function contextIds(): {
  context_document_ids: number[];
  context_conversation_ids: number[];
  attachment_ids: number[];
} {
  return {
    context_document_ids: attachedDocuments.value.map((item) => item.id),
    context_conversation_ids: attachedConversations.value.map((item) => item.id),
    attachment_ids: attachedFiles.value.map((item) => item.id),
  };
}

function pickFile(): void {
  fileInputRef.value?.click();
}

async function onFilesSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.value = "";
  if (!files.length) return;
  if (!conversation.value) await load();
  if (!conversation.value) return;
  uploading.value = true;
  try {
    for (const file of files) {
      const uploaded = await api.upload<any>(
        `/conversations/${conversation.value.id}/attachments`,
        file,
      );
      attachedFiles.value.push(uploaded);
      toast.push(`已上传附件：${uploaded.file_name}`);
    }
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "附件上传失败", "error");
  } finally {
    uploading.value = false;
  }
}

async function removeAttachment(id: number): Promise<void> {
  attachedFiles.value = attachedFiles.value.filter((item) => item.id !== id);
  try {
    await api.delete(`/conversations/attachments/${id}`);
  } catch {
    // 附件可能已随消息发送，忽略删除失败
  }
}

function messageAttachments(message: any): any[] {
  return message.message_metadata?.attachments || [];
}

async function downloadAttachment(file: any): Promise<void> {
  try {
    await api.download(
      `/conversations/attachments/${file.id}/download`,
      file.file_name || `attachment-${file.id}`,
    );
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "附件下载失败", "error");
  }
}

async function ensureConversation(): Promise<void> {
  if (props.conversationId) {
    const data = await api.get<any>(`/conversations/${props.conversationId}`);
    applyDetail(data);
    return;
  }
  if (props.employeeId) {
    const data = await api.post<any>("/conversations", {
      mode: "direct",
      employee_id: props.employeeId,
    });
    applyDetail(data);
    return;
  }
  conversation.value = null;
  members.value = [];
  messages.value = [];
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    await ensureConversation();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载会话失败";
  } finally {
    loading.value = false;
  }
}

function stopStream(): void {
  abortController.value?.abort();
}

function applyStreamEvent(event: any): void {
  if (event.type === "user_message") {
    messages.value.push(event.message);
    draft.value = "";
    mentionOpen.value = false;
    explicitTargets.value = [];
    clearAttachments();
    streamStopped.value = false;
    scrollBottom();
    return;
  }
  if (event.type === "reply_start") {
    messages.value.push({
      id: `stream-${event.employee_id}-${Date.now()}`,
      conversation_id: conversation.value?.id,
      employee_id: event.employee_id,
      employee_name: event.employee_name,
      role: "assistant",
      content: "",
      tool_calls: [],
      tokens: 0,
      cost: 0,
      trace_id: null,
      status: "streaming",
      message_metadata: {},
      created_at: new Date().toISOString(),
      streaming: true,
    });
    scrollBottom();
    return;
  }
  if (event.type === "delta") {
    const target = [...messages.value]
      .reverse()
      .find(
        (item) => item.streaming && item.employee_id === event.employee_id,
      );
    if (target) {
      target.content += event.content;
      scrollBottom();
    }
    return;
  }
  if (event.type === "reply_done") {
    const index = messages.value.findIndex(
      (item) => item.streaming && item.employee_id === event.message.employee_id,
    );
    if (index >= 0) messages.value.splice(index, 1, event.message);
    else messages.value.push(event.message);
    scrollBottom();
    return;
  }
  if (event.type === "error") {
    const index = messages.value.findIndex(
      (item) => item.streaming && item.employee_id === event.employee_id,
    );
    if (index >= 0) messages.value.splice(index, 1);
    toast.push(event.message || "生成失败", "error");
  }
}

async function send(): Promise<void> {
  const content = draft.value.trim();
  if (!content || sending.value) return;
  if (!conversation.value) await load();
  if (!conversation.value) return;
  if (isGroup.value && routingMode.value === "explicit" && !explicitTargets.value.length) {
    error.value = "指定回复需要先选择至少一名员工（输入 @ 或点选成员）";
    toast.push(error.value, "error");
    return;
  }
  sending.value = true;
  error.value = "";
  streamStopped.value = false;
  const controller = new AbortController();
  abortController.value = controller;
  const token = localStorage.getItem("de.token");
  try {
    const response = await fetch(
      `${API_BASE}/conversations/${conversation.value.id}/messages/stream`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          content,
          routing_mode: isGroup.value ? routingMode.value : "auto",
          target_employee_ids:
            isGroup.value && routingMode.value === "explicit"
              ? [...explicitTargets.value]
              : [],
          ...contextIds(),
        }),
        signal: controller.signal,
      },
    );
    if (response.status === 401) {
      localStorage.removeItem("de.token");
      window.location.hash = "#/login";
      throw new Error("登录已过期，请重新登录");
    }
    if (!response.ok) {
      let message = `流式请求失败（${response.status}）`;
      try {
        const payload = await response.json();
        message = payload?.message || message;
      } catch {
        // ignore
      }
      throw new Error(message);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error("当前浏览器不支持流式响应");
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk
          .split("\n")
          .find((item) => item.startsWith("data:"));
        if (!line) continue;
        try {
          applyStreamEvent(JSON.parse(line.slice(5).trim()));
        } catch {
          // 忽略不完整/非法片段
        }
      }
    }
    emit("updated");
  } catch (err) {
    if (controller.signal.aborted) {
      streamStopped.value = true;
      for (const message of messages.value) {
        if (message.streaming) {
          message.streaming = false;
          message.status = "cancelled";
          if (!message.content) message.content = "（已停止生成）";
        }
      }
      toast.push("已停止生成");
    } else {
      error.value = err instanceof Error ? err.message : "发送失败";
      toast.push(error.value, "error");
      for (const message of messages.value) {
        if (message.streaming) message.streaming = false;
      }
    }
  } finally {
    sending.value = false;
    abortController.value = null;
    if (routingMode.value === "explicit") routingMode.value = "auto";
  }
}

async function createTask(): Promise<void> {
  const content = draft.value.trim();
  if (!content || sending.value) return;
  if (!conversation.value) await load();
  if (!conversation.value) return;
  let employeeId: number | null = null;
  if (isGroup.value) {
    employeeId = taskEmployeeId.value ?? members.value[0]?.employee_id ?? null;
    if (!employeeId) {
      toast.push("请选择任务执行员工", "error");
      return;
    }
  }
  sending.value = true;
  error.value = "";
  try {
    const result = await api.post<any>(
      `/conversations/${conversation.value.id}/tasks`,
      {
        content,
        employee_id: employeeId,
        ...contextIds(),
      },
    );
    messages.value.push(result.message);
    toast.push(`任务已创建：${result.task.title}`);
    draft.value = "";
    mentionOpen.value = false;
    clearAttachments();
    composerMode.value = "message";
    scrollBottom();
    emit("updated");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建任务失败";
    toast.push(error.value, "error");
  } finally {
    sending.value = false;
  }
}

function submit(): void {
  if (composerMode.value === "task") void createTask();
  else void send();
}

function retryLast(): void {
  const last = [...messages.value]
    .reverse()
    .find(
      (item) =>
        item.role === "user" &&
        item.message_metadata?.kind !== "task_created" &&
        (item.content || "").trim(),
    );
  if (!last) {
    toast.push("没有可重试的消息", "error");
    return;
  }
  draft.value = last.content;
  nextTick(() => void send());
}

function approveLatestPending(): void {
  const target = [...messages.value]
    .reverse()
    .find(
      (item) =>
        item.role === "assistant" &&
        (item.message_metadata?.pending_tools || []).length,
    );
  if (!target) {
    toast.push("当前没有待确认工具", "error");
    return;
  }
  void decideAll(target, true);
}

function runSlash(name: string): void {
  draft.value = "";
  mentionOpen.value = false;
  if (name === "任务") {
    composerMode.value = "task";
    nextTick(() => textareaRef.value?.focus());
    return;
  }
  if (name === "确认") {
    approveLatestPending();
    return;
  }
  if (name === "总结") {
    draft.value = "请总结当前对话的要点，并列出接下来需要我确认或跟进的事项。";
    nextTick(() => void send());
    return;
  }
  if (name === "重试") {
    retryLast();
  }
}

function openTaskFromMessage(message: any): void {
  const metadata = message.message_metadata || {};
  if (!metadata.task_id) return;
  drawer.open(TaskDetailDrawer, {
    id: metadata.task_id,
    employeeName: metadata.employee_name,
  });
}

function messageContexts(message: any): { type: string; label: string }[] {
  const metadata = message.message_metadata || {};
  return [
    ...(metadata.context_documents || []).map((item: any) => ({
      type: "文件",
      label: item.title,
    })),
    ...(metadata.context_conversations || []).map((item: any) => ({
      type: "会话",
      label: item.title,
    })),
  ];
}

function detectMention(): void {
  if (!conversation.value) {
    mentionOpen.value = false;
    return;
  }
  const element = textareaRef.value;
  if (!element) return;
  const caret = element.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, caret);
  const match = /(^|\s)@([^\s@]*)$/.exec(before);
  if (!match) {
    mentionOpen.value = false;
    return;
  }
  mentionStart.value = caret - match[2].length - 1;
  mentionQuery.value = match[2];
  mentionIndex.value = 0;
  mentionOpen.value = true;
}

function insertMentionText(label: string): void {
  const element = textareaRef.value;
  const caret = element?.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, mentionStart.value);
  const after = draft.value.slice(caret);
  const inserted = `@${label} `;
  draft.value = `${before}${inserted}${after}`;
  mentionOpen.value = false;
  mentionQuery.value = "";
  nextTick(() => {
    element?.focus();
    const position = before.length + inserted.length;
    element?.setSelectionRange(position, position);
  });
}

function selectMentionItem(item: any): void {
  if (item.type === "employee") {
    if (composerMode.value === "task") {
      taskEmployeeId.value = item.data.employee_id;
    } else {
      if (!explicitTargets.value.includes(item.data.employee_id)) {
        explicitTargets.value.push(item.data.employee_id);
      }
      routingMode.value = "explicit";
    }
  } else if (item.type === "document") {
    if (!attachedDocuments.value.some((doc) => doc.id === item.data.id)) {
      attachedDocuments.value.push(item.data);
    }
  } else if (item.type === "conversation") {
    if (!attachedConversations.value.some((row) => row.id === item.data.id)) {
      attachedConversations.value.push(item.data);
    }
  }
  insertMentionText(item.label);
}

function removeDocument(id: number): void {
  attachedDocuments.value = attachedDocuments.value.filter((item) => item.id !== id);
}

function removeConversation(id: number): void {
  attachedConversations.value = attachedConversations.value.filter(
    (item) => item.id !== id,
  );
}

function toggleTarget(employeeId: number): void {
  const index = explicitTargets.value.indexOf(employeeId);
  if (index >= 0) explicitTargets.value.splice(index, 1);
  else explicitTargets.value.push(employeeId);
}

function onKeydown(event: KeyboardEvent): void {
  if (slashOpen.value && slashCandidates.value.length) {
    if (event.key === "Escape") {
      event.preventDefault();
      draft.value = "";
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      slashIndex.value = (slashIndex.value + 1) % slashCandidates.value.length;
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      slashIndex.value =
        (slashIndex.value - 1 + slashCandidates.value.length) %
        slashCandidates.value.length;
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      runSlash(slashCandidates.value[slashIndex.value].name);
      return;
    }
  }
  if (mentionOpen.value && mentionItems.value.length) {
    if (event.key === "Escape") {
      event.preventDefault();
      mentionOpen.value = false;
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      mentionIndex.value = (mentionIndex.value + 1) % mentionItems.value.length;
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      mentionIndex.value =
        (mentionIndex.value - 1 + mentionItems.value.length) %
        mentionItems.value.length;
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      selectMentionItem(mentionItems.value[mentionIndex.value]);
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
}

async function decideTool(
  message: any,
  index: number,
  approved: boolean,
): Promise<void> {
  if (!conversation.value || decidingKey.value) return;
  decidingKey.value = `${message.id}:${index}`;
  try {
    const result = await api.post<any>(
      `/conversations/${conversation.value.id}/tool-decisions`,
      { message_id: message.id, decisions: [{ index, approved }] },
    );
    message.message_metadata = {
      ...(message.message_metadata || {}),
      pending_tools: result.remaining || [],
    };
    messages.value.push(result.message);
    toast.push(approved ? "工具已批准执行" : "工具已拒绝");
    scrollBottom();
    emit("updated");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "审批失败", "error");
  } finally {
    decidingKey.value = "";
  }
}

async function decideAll(message: any, approved: boolean): Promise<void> {
  if (!conversation.value || decidingKey.value) return;
  const pending = message.message_metadata?.pending_tools || [];
  if (!pending.length) return;
  decidingKey.value = `${message.id}:all`;
  try {
    const result = await api.post<any>(
      `/conversations/${conversation.value.id}/tool-decisions`,
      {
        message_id: message.id,
        decisions: pending.map((_: any, index: number) => ({ index, approved })),
      },
    );
    message.message_metadata = {
      ...(message.message_metadata || {}),
      pending_tools: result.remaining || [],
    };
    messages.value.push(result.message);
    toast.push(approved ? "已批准全部工具" : "已拒绝全部工具");
    scrollBottom();
    emit("updated");
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "审批失败", "error");
  } finally {
    decidingKey.value = "";
  }
}

function decisionLabel(decision?: string): string {
  if (decision === "deny") return "红线拦截";
  if (decision === "ask") return "待确认";
  if (decision === "confirmed") return "已确认执行";
  if (decision === "allow") return "已执行";
  if (decision === "rejected") return "已拒绝";
  if (decision === "error") return "执行失败";
  return decision || "工具";
}

function toolCallsOf(message: any): any[] {
  const calls = message.tool_calls || [];
  // 有独立审批卡片时，不再重复渲染同一条 ask 工具轨迹。
  if (message.message_metadata?.pending_tools?.length) {
    return calls.filter((call: any) => !call.requires_confirmation);
  }
  return calls;
}

function outputText(value: unknown): string {
  if (value === undefined || value === null) return "";
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return text.length > 1200 ? `${text.slice(0, 1200)}…` : text;
}

onMounted(async () => {
  await load();
  await loadContextOptions();
});
watch(
  () => [props.employeeId, props.conversationId],
  () => {
    routingMode.value = "auto";
    explicitTargets.value = [];
    mentionOpen.value = false;
    clearAttachments();
    composerMode.value = "message";
    taskEmployeeId.value = null;
    void load();
  },
);
watch(slashQuery, () => {
  slashIndex.value = 0;
});
watch(members, (rows) => {
  if (!taskEmployeeId.value && rows.length) {
    taskEmployeeId.value = rows[0].employee_id;
  }
});
</script>

<template>
  <div class="chat-panel" :class="{ compact }">
    <div class="chat-head">
      <div class="chat-title">
        <span class="live-dot" />
        <div>
          <b>{{ title }}</b>
          <small v-if="conversation?.mode === 'group'">
            群聊 · {{ members.length }} 位数字员工
          </small>
          <small v-else-if="members.length">
            {{ members[0].agent_name || "未绑定 Agent" }}
          </small>
        </div>
      </div>
      <div class="chat-head-actions">
        <select
          v-if="conversation?.mode === 'group'"
          v-model="routingMode"
          class="route-select"
          title="群聊回复方式"
        >
          <option value="auto">自动路由</option>
          <option value="all">全员回复</option>
          <option value="explicit">指定员工</option>
        </select>
        <button class="btn btn-sm btn-ghost" type="button" @click="load">
          <AppIcon name="refresh" />
        </button>
      </div>
    </div>

    <div v-if="isGroup && routingMode === 'explicit'" class="target-bar">
      <span class="target-label">指定回复</span>
      <button
        v-for="member in members"
        :key="member.employee_id"
        type="button"
        class="target-chip"
        :class="{ active: explicitTargets.includes(member.employee_id) }"
        @click="toggleTarget(member.employee_id)"
      >
        @{{ member.name }}
      </button>
      <span v-if="!explicitTargets.length" class="target-hint muted">
        点选成员或在输入框输入 @
      </span>
    </div>

    <div ref="bodyRef" class="chat-body">
      <div v-if="loading" class="chat-empty muted">正在连接数字员工…</div>
      <div v-else-if="!conversation" class="chat-empty">
        <b>选择一位数字员工开始对话</b>
        <p class="muted">对话中可以直接指挥员工调用工具，并查看 Token 消耗。</p>
      </div>
      <div v-else-if="!messages.length" class="chat-empty">
        <b>开始一段工作对话</b>
        <p class="muted">
          例如：“帮我核对 A 客户回款，并生成一条催收待办。”
        </p>
      </div>

      <template v-else>
        <div
          v-for="message in messages"
          :key="message.id"
          class="message"
          :class="message.role"
        >
          <div v-if="message.role === 'assistant'" class="message-avatar">
            {{ (memberName(message.employee_id) || "E").slice(0, 1) }}
          </div>
          <div class="bubble-wrap">
            <div class="bubble-meta">
              <span v-if="message.role === 'assistant'" class="speaker">
                {{ memberName(message.employee_id) }}
              </span>
              <span v-else class="speaker">我</span>
              <span class="time">{{ fmtDate(message.created_at) }}</span>
              <span v-if="message.tokens" class="token-badge">
                {{ message.tokens }} tokens
              </span>
            </div>
            <div class="bubble" :class="{ user: message.role === 'user' }">
              <div
                v-if="message.message_metadata?.kind === 'task_created'"
                class="task-created-card"
              >
                <div class="task-created-main">
                  <span class="task-created-label">已创建任务</span>
                  <b>
                    #{{ message.message_metadata.task_id }} ·
                    {{ message.message_metadata.title }}
                  </b>
                  <small class="muted">
                    {{ message.message_metadata.employee_name || "数字员工" }}
                  </small>
                </div>
                <button
                  class="btn btn-sm"
                  type="button"
                  @click="openTaskFromMessage(message)"
                >
                  查看任务
                </button>
              </div>
              <div
                v-if="messageContexts(message).length"
                class="message-context"
              >
                <span
                  v-for="(context, contextIndex) in messageContexts(message)"
                  :key="contextIndex"
                  class="context-tag"
                >
                  {{ context.type }} · {{ context.label }}
                </span>
              </div>
              <div
                v-if="messageAttachments(message).length"
                class="message-attachments"
              >
                <button
                  v-for="file in messageAttachments(message)"
                  :key="`att-${file.id}`"
                  type="button"
                  class="attachment-link"
                  @click="downloadAttachment(file)"
                >
                  附件 · {{ file.file_name }}
                </button>
              </div>
              <div v-if="message.streaming && !message.content" class="typing">
                <span /><span /><span />
              </div>
              <div v-if="message.content" class="content">{{ message.content }}</div>

              <div v-if="toolCallsOf(message).length" class="tool-stack">
                <div
                  v-for="(call, index) in toolCallsOf(message)"
                  :key="`${message.id}-${index}`"
                  class="tool-card"
                  :class="call.decision"
                >
                  <div class="tool-head">
                    <span class="tool-name mono">{{ call.tool }}</span>
                    <span class="tool-decision">{{ decisionLabel(call.decision) }}</span>
                    <span v-if="call.latency_ms" class="muted">
                      {{ call.latency_ms }}ms
                    </span>
                  </div>
                  <div class="tool-args mono">
                    {{ outputText(call.arguments) || "{}" }}
                  </div>
                  <div v-if="call.error" class="tool-error">{{ call.error }}</div>
                  <details v-if="call.output" class="tool-output">
                    <summary>查看结果</summary>
                    <pre>{{ outputText(call.output) }}</pre>
                  </details>
                </div>
              </div>

              <div
                v-if="message.message_metadata?.pending_tools?.length"
                class="approval-block"
              >
                <div class="approval-head">
                  <div>
                    <b>待审批工具 · {{ message.message_metadata.pending_tools.length }}</b>
                    <small>批准后立即执行；拒绝不会调用工具。</small>
                  </div>
                  <div class="approval-bulk">
                    <button
                      class="btn btn-sm btn-ghost"
                      type="button"
                      :disabled="!!decidingKey"
                      @click="decideAll(message, false)"
                    >
                      全部拒绝
                    </button>
                    <button
                      class="btn btn-sm btn-primary"
                      type="button"
                      :disabled="!!decidingKey"
                      @click="decideAll(message, true)"
                    >
                      全部批准
                    </button>
                  </div>
                </div>
                <div
                  v-for="(pending, index) in message.message_metadata.pending_tools"
                  :key="`${message.id}-pending-${index}`"
                  class="approval-card"
                >
                  <div class="approval-title">
                    <span class="mono">{{ pending.tool }}</span>
                    <span class="approval-tag">需确认</span>
                  </div>
                  <p class="approval-reason">
                    {{ pending.reason || "岗位契约要求人工确认" }}
                  </p>
                  <pre class="approval-args">{{ outputText(pending.arguments) || "{}" }}</pre>
                  <div class="approval-actions">
                    <button
                      class="btn btn-sm"
                      type="button"
                      :disabled="!!decidingKey"
                      @click="decideTool(message, index, false)"
                    >
                      {{ decidingKey === `${message.id}:${index}` ? "处理中…" : "拒绝" }}
                    </button>
                    <button
                      class="btn btn-sm btn-primary"
                      type="button"
                      :disabled="!!decidingKey"
                      @click="decideTool(message, index, true)"
                    >
                      {{ decidingKey === `${message.id}:${index}` ? "处理中…" : "批准执行" }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div v-if="streamStopped && !sending" class="stream-stopped">
      <span>已停止生成，回复未完整保存。</span>
      <button class="btn btn-sm" type="button" @click="retryLast">重试</button>
    </div>

    <div v-if="error" class="chat-error">{{ error }}</div>

    <div class="composer">
      <div
        v-if="slashOpen && slashCandidates.length"
        class="mention-menu slash-menu"
      >
        <div class="menu-section">调用指令</div>
        <button
          v-for="(command, index) in slashCandidates"
          :key="command.name"
          type="button"
          class="mention-item"
          :class="{ active: index === slashIndex }"
          @mousedown.prevent="runSlash(command.name)"
        >
          <span class="slash-symbol">/</span>
          <span class="mention-meta">
            <b>/{{ command.name }}</b>
            <small>{{ command.desc }}</small>
          </span>
        </button>
      </div>

      <div
        v-if="mentionOpen && mentionItems.length && !slashOpen"
        class="mention-menu"
      >
        <template v-for="section in mentionSections" :key="section.type">
          <div class="menu-section">{{ section.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.key"
            type="button"
            class="mention-item"
            :class="{ active: item.index === mentionIndex }"
            @mousedown.prevent="selectMentionItem(item)"
          >
            <span class="mention-avatar">
              {{
                section.type === "employee"
                  ? (item.label || "E").slice(0, 1)
                  : section.type === "document"
                    ? "文"
                    : "话"
              }}
            </span>
            <span class="mention-meta">
              <b>{{ item.label }}</b>
              <small>{{ item.sub }}</small>
            </span>
          </button>
        </template>
      </div>

      <div class="composer-modes">
        <button
          type="button"
          class="mode-btn"
          :class="{ active: composerMode === 'message' }"
          @click="composerMode = 'message'"
        >
          发消息
        </button>
        <button
          type="button"
          class="mode-btn"
          :class="{ active: composerMode === 'task' }"
          @click="composerMode = 'task'"
        >
          创建任务
        </button>
        <span v-if="composerMode === 'task' && isGroup" class="task-worker">
          <span>执行员工</span>
          <select v-model.number="taskEmployeeId">
            <option
              v-for="member in members"
              :key="member.employee_id"
              :value="member.employee_id"
            >
              {{ member.name }}
            </option>
          </select>
        </span>
        <button
          type="button"
          class="mode-btn attach-btn"
          :disabled="uploading || sending"
          @click="pickFile"
        >
          {{ uploading ? "上传中…" : "+ 附件" }}
        </button>
        <input
          ref="fileInputRef"
          type="file"
          multiple
          class="hidden-file"
          accept=".txt,.md,.markdown,.csv,.json,.log,.yaml,.yml,.pdf,.docx,.xlsx,.png,.jpg,.jpeg,.webp,.gif"
          @change="onFilesSelected"
        />
        <span class="mode-hint muted">输入 / 调用指令，@ 引用文件或会话</span>
      </div>

      <div
        v-if="
          attachedDocuments.length ||
          attachedConversations.length ||
          attachedFiles.length
        "
        class="context-bar"
      >
        <span class="context-label">引用</span>
        <button
          v-for="document in attachedDocuments"
          :key="`doc-${document.id}`"
          type="button"
          class="context-chip"
          @click="removeDocument(document.id)"
        >
          文件 · {{ document.title }} ×
        </button>
        <button
          v-for="item in attachedConversations"
          :key="`conv-${item.id}`"
          type="button"
          class="context-chip"
          @click="removeConversation(item.id)"
        >
          会话 · {{ item.title || `#${item.id}` }} ×
        </button>
        <button
          v-for="file in attachedFiles"
          :key="`att-${file.id}`"
          type="button"
          class="context-chip"
          @click="removeAttachment(file.id)"
        >
          附件 · {{ file.file_name }} ×
        </button>
      </div>

      <textarea
        ref="textareaRef"
        v-model="draft"
        rows="2"
        :placeholder="
          composerMode === 'task'
            ? '描述任务目标，Enter 创建任务，Shift+Enter 换行'
            : isGroup
              ? '输入消息；@ 引用员工/文件/会话，/ 调用指令'
              : '输入工作指令；@ 引用文件/会话，/ 调用指令'
        "
        :disabled="sending"
        @input="detectMention"
        @click="detectMention"
        @keydown="onKeydown"
      />
      <div class="composer-foot">
        <span class="muted">
          <template v-if="composerMode === 'task'">
            任务会进入任务中心，由 Worker 领取执行。
          </template>
          <template v-else-if="targetMembers.length">
            本次回复：{{ targetMembers.map((member) => member.name).join("、") }}
          </template>
          <template v-else>
            工具调用会遵守岗位契约；红线操作不会执行。
          </template>
        </span>
        <button
          v-if="sending && composerMode === 'message'"
          class="btn btn-sm btn-danger"
          type="button"
          @click="stopStream"
        >
          停止
        </button>
        <button
          v-else
          class="btn btn-primary btn-sm"
          :disabled="sending || !draft.trim()"
          @click="submit()"
        >
          {{
            sending
              ? "创建中…"
              : composerMode === "task"
                ? "创建任务"
                : "发送"
          }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 420px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  overflow: hidden;
}
.chat-panel.compact {
  border: none;
  border-radius: 0;
}
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-2);
}
.chat-title {
  display: flex;
  align-items: center;
  gap: 9px;
}
.chat-title > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.chat-title b {
  font-size: 13px;
}
.chat-title small {
  font-size: 10.5px;
  color: var(--dim);
}
.chat-head-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}
.route-select {
  height: 26px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--dim);
  font-size: 10px;
  padding: 0 5px;
  outline: none;
}
.target-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  padding: 7px 14px;
  border-bottom: 1px solid var(--line);
  background: rgba(232, 163, 61, 0.05);
  font-size: 10.5px;
}
.target-label {
  color: var(--dim);
  margin-right: 2px;
}
.target-chip {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--dim);
  font-size: 10px;
  padding: 2px 8px;
  cursor: pointer;
}
.target-chip.active {
  border-color: var(--amber);
  color: var(--amber);
  background: rgba(232, 163, 61, 0.12);
}
.target-hint {
  font-size: 10px;
}
.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4fd1b0;
  box-shadow: 0 0 0 3px rgba(79, 209, 176, 0.12);
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat-empty {
  margin: auto;
  text-align: center;
  max-width: 300px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.chat-empty p {
  margin: 0;
  line-height: 1.6;
}
.message {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.message.user {
  justify-content: flex-end;
}
.message-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-size: 11px;
  font-weight: 700;
  flex: 0 0 auto;
}
.bubble-wrap {
  max-width: 86%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.message.user .bubble-wrap {
  align-items: flex-end;
}
.bubble-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--dim);
}
.speaker {
  color: var(--text);
  font-weight: 600;
}
.token-badge {
  font-family: var(--mono);
  color: var(--amber);
}
.bubble {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-2);
  padding: 9px 11px;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: color-mix(in srgb, var(--amber) 15%, var(--panel-2));
  border-color: color-mix(in srgb, var(--amber) 30%, var(--line));
}
.tool-stack {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-card {
  border: 1px solid var(--line);
  border-left: 2px solid #4fd1b0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  padding: 7px 9px;
  font-size: 11px;
}
.tool-card.deny {
  border-left-color: var(--coral);
}
.tool-card.ask {
  border-left-color: var(--amber);
}
.tool-card.rejected,
.tool-card.error {
  border-left-color: var(--coral);
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 7px;
}
.tool-name {
  color: var(--text);
  font-size: 10.5px;
}
.tool-decision {
  font-size: 9.5px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 6px;
}
.tool-args {
  margin-top: 5px;
  color: var(--dim);
  font-size: 10px;
  white-space: pre-wrap;
  word-break: break-all;
}
.tool-error {
  margin-top: 5px;
  color: var(--coral);
  font-size: 10.5px;
}
.tool-output summary {
  cursor: pointer;
  color: var(--dim);
  font-size: 10px;
  margin-top: 5px;
}
.tool-output pre {
  margin: 5px 0 0;
  max-height: 180px;
  overflow: auto;
  font-size: 10px;
  color: var(--dim);
}
.approval-block {
  margin-top: 9px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.approval-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.approval-head > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.approval-head b {
  font-size: 11px;
  color: var(--amber);
}
.approval-head small {
  font-size: 9.5px;
  color: var(--dim);
}
.approval-bulk {
  display: flex;
  gap: 5px;
  flex-shrink: 0;
}
.approval-card {
  border: 1px solid color-mix(in srgb, var(--amber) 35%, var(--line));
  border-radius: 10px;
  background: rgba(232, 163, 61, 0.05);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.approval-title {
  display: flex;
  align-items: center;
  gap: 7px;
}
.approval-title .mono {
  font-size: 11px;
  color: var(--text);
}
.approval-tag {
  font-size: 9px;
  color: var(--amber);
  border: 1px solid color-mix(in srgb, var(--amber) 45%, transparent);
  border-radius: 999px;
  padding: 1px 6px;
}
.approval-reason {
  margin: 0;
  font-size: 10.5px;
  color: var(--dim);
  line-height: 1.5;
}
.approval-args {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: rgba(0, 0, 0, 0.18);
  padding: 6px 8px;
  font-size: 10px;
  color: var(--dim);
  white-space: pre-wrap;
  word-break: break-all;
}
.approval-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.chat-error {
  padding: 6px 12px;
  color: var(--coral);
  font-size: 11px;
  border-top: 1px solid var(--line);
}
.composer {
  position: relative;
  border-top: 1px solid var(--line);
  padding: 9px 11px 10px;
  background: var(--panel-2);
}
.mention-menu {
  position: absolute;
  left: 11px;
  right: 11px;
  bottom: calc(100% - 2px);
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--line-strong);
  border-radius: 11px;
  background: #131d27;
  box-shadow: 0 -18px 40px rgba(0, 0, 0, 0.45);
  padding: 5px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mention-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  text-align: left;
  padding: 6px 8px;
  cursor: pointer;
}
.mention-item.active,
.mention-item:hover {
  background: rgba(232, 163, 61, 0.12);
}
.mention-avatar {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-size: 10.5px;
  font-weight: 700;
}
.mention-meta {
  display: flex;
  flex-direction: column;
}
.mention-meta b {
  font-size: 11.5px;
}
.mention-meta small {
  font-size: 9.5px;
  color: var(--dim);
}
.menu-section {
  padding: 6px 8px 3px;
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--dim);
}
.slash-symbol {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: rgba(232, 163, 61, 0.14);
  color: var(--amber);
  font-family: var(--mono);
  font-size: 12px;
  flex-shrink: 0;
}
.composer-modes {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 7px;
}
.mode-btn {
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--dim);
  font-size: 10.5px;
  padding: 3px 10px;
  cursor: pointer;
}
.mode-btn.active {
  color: var(--amber);
  border-color: color-mix(in srgb, var(--amber) 40%, var(--line));
  background: rgba(232, 163, 61, 0.1);
}
.mode-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.hidden-file {
  display: none;
}
.typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--dim);
  animation: typing-dot 1.2s infinite ease-in-out;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes typing-dot {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.attachment-link {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.02);
  color: var(--text);
  font-size: 9.5px;
  padding: 2px 8px;
  cursor: pointer;
}
.attachment-link:hover {
  border-color: var(--amber);
  color: var(--amber);
}
.stream-stopped {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 12px;
  border-top: 1px solid var(--line);
  background: rgba(232, 163, 61, 0.06);
  font-size: 10.5px;
  color: var(--dim);
}
.task-worker {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--dim);
}
.task-worker select {
  height: 24px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text);
  font-size: 10px;
  padding: 0 5px;
  outline: none;
}
.mode-hint {
  margin-left: auto;
  font-size: 9.5px;
}
.context-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 7px;
}
.context-label {
  font-size: 9.5px;
  color: var(--dim);
}
.context-chip {
  border: 1px solid color-mix(in srgb, var(--amber) 35%, var(--line));
  border-radius: 999px;
  background: rgba(232, 163, 61, 0.08);
  color: var(--amber);
  font-size: 9.5px;
  padding: 2px 8px;
  cursor: pointer;
}
.message-context {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.context-tag {
  font-size: 9px;
  color: var(--dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 6px;
}
.task-created-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid color-mix(in srgb, var(--amber) 40%, var(--line));
  border-radius: 9px;
  background: rgba(232, 163, 61, 0.07);
  padding: 8px 10px;
  margin-bottom: 6px;
}
.task-created-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.task-created-label {
  font-size: 9.5px;
  color: var(--amber);
}
.task-created-main b {
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-created-main small {
  font-size: 9.5px;
}
.composer textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  color: var(--text);
  padding: 8px 10px;
  font-size: 12.5px;
  line-height: 1.6;
  outline: none;
}
.composer textarea:focus {
  border-color: var(--line-strong);
}
.composer-foot {
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.composer-foot .muted {
  font-size: 9.5px;
  line-height: 1.4;
}
</style>
