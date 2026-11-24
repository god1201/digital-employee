<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import ArtifactDrawer from "@/components/ArtifactDrawer.vue";
import AttributionDrawer from "@/components/AttributionDrawer.vue";
import DataTable from "@/components/DataTable.vue";
import EvaluationSuiteDrawer from "@/components/EvaluationSuiteDrawer.vue";
import InterventionDrawer from "@/components/InterventionDrawer.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import TrialDrawer from "@/components/TrialDrawer.vue";
import WeeklyReviewDrawer from "@/components/WeeklyReviewDrawer.vue";
import { useDrawerStore } from "@/stores/drawer";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface Employee {
  id: number;
  name: string;
  code: string;
}

interface Preference {
  id: number;
  employee_id: number;
  key: string;
  value: string;
  scope: string;
  source: string;
  status: string;
  updated_at: string;
}

interface Intervention {
  id: number;
  employee_id?: number | null;
  instance_id?: number | null;
  source_type: string;
  diff: Array<Record<string, unknown>>;
  status: string;
  created_at: string;
}

interface Artifact {
  id: number;
  employee_id?: number | null;
  target_layer: string;
  attribution: string;
  risk: string;
  scope: string;
  status: string;
  version: number;
  created_at: string;
}

interface Attribution {
  id: number;
  employee_id?: number | null;
  category: string;
  category_label: string;
  confidence: number;
  routed_action: string;
  suggestion: string;
  status: string;
  created_at: string;
}

interface EvaluationSuite {
  id: number;
  employee_id?: number | null;
  name: string;
  code: string;
  threshold: number;
  enforce_on_activate: boolean;
  enabled: boolean;
  created_at: string;
}

interface Trial {
  id: number;
  employee_id: number;
  mode: string;
  status: string;
  decision?: string | null;
  threshold: number;
  metrics: Record<string, unknown>;
  created_at: string;
}

interface TimelineItem {
  type: "intervention" | "artifact" | "attribution" | "trial";
  id: number;
  employee_id?: number | null;
  title: string;
  status: string;
  category: string;
  summary: string;
  created_at: string;
}

interface LearningQuestion {
  id: number;
  employee_id: number;
  question: string;
  options: Array<{ value?: string; label?: string }>;
  status: string;
  answer?: string | null;
  created_at: string;
}

interface WeeklyReview {
  id: number;
  employee_id?: number | null;
  period_start: string;
  period_end: string;
  summary: string;
  metrics: Record<string, any>;
  created_at: string;
}

interface ExpertCandidate {
  instance_id: number;
  employee_id?: number | null;
  title: string;
  attempt: number;
  steps: number;
  takeover: number;
  quality: string;
  finished_at?: string | null;
}

interface ImplicitSignal {
  id: number;
  employee_id?: number | null;
  instance_id?: number | null;
  signal_type: string;
  content: string;
  weight: number;
  created_at: string;
}

type TabKey =
  | "preferences"
  | "interventions"
  | "artifacts"
  | "attributions"
  | "evaluations"
  | "trials"
  | "timeline"
  | "questions"
  | "reviews"
  | "experts"
  | "implicit";

const tab = ref<TabKey>("preferences");
const employees = ref<Employee[]>([]);
const preferences = ref<Preference[]>([]);
const interventions = ref<Intervention[]>([]);
const artifacts = ref<Artifact[]>([]);
const attributions = ref<Attribution[]>([]);
const suites = ref<EvaluationSuite[]>([]);
const trials = ref<Trial[]>([]);
const timeline = ref<TimelineItem[]>([]);
const questions = ref<LearningQuestion[]>([]);
const reviews = ref<WeeklyReview[]>([]);
const candidates = ref<ExpertCandidate[]>([]);
const implicitSignals = ref<ImplicitSignal[]>([]);
const employeeFilter = ref<number | "">("");
const loading = ref(false);

const drawer = useDrawerStore();
const modal = useModalStore();
const toast = useToastStore();

const employeeMap = computed(() =>
  Object.fromEntries(employees.value.map((item) => [item.id, item.name])),
);

function nameOf(id?: number | null): string {
  return id ? employeeMap.value[id] || `#${id}` : "—";
}

function filterByEmployee<T extends { employee_id?: number | null }>(rows: T[]): T[] {
  if (employeeFilter.value === "") return rows;
  return rows.filter((row) => row.employee_id === employeeFilter.value);
}

const filteredPreferences = computed(() => filterByEmployee(preferences.value));
const filteredInterventions = computed(() => filterByEmployee(interventions.value));
const filteredArtifacts = computed(() => filterByEmployee(artifacts.value));
const filteredAttributions = computed(() => filterByEmployee(attributions.value));
const filteredSuites = computed(() => filterByEmployee(suites.value));
const filteredTrials = computed(() => filterByEmployee(trials.value));
const filteredTimeline = computed(() => filterByEmployee(timeline.value));
const filteredQuestions = computed(() => filterByEmployee(questions.value));
const filteredReviews = computed(() => filterByEmployee(reviews.value));
const filteredCandidates = computed(() => filterByEmployee(candidates.value));
const filteredImplicit = computed(() => filterByEmployee(implicitSignals.value));

const employeeOptions = computed(() => [
  { value: "", label: "不绑定员工" },
  ...employees.value.map((item) => ({
    value: item.id,
    label: `${item.name} · ${item.code}`,
  })),
]);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [
      employeeData,
      preferenceData,
      interventionData,
      artifactData,
      attributionData,
      suiteData,
      trialData,
      timelineData,
      questionData,
      reviewData,
      candidateData,
      implicitData,
    ] = await Promise.all([
      api.get<Paged<Employee>>("/digital-employees?page_size=200"),
      api.get<Paged<Preference>>("/preferences?page_size=200"),
      api.get<Paged<Intervention>>("/interventions?page_size=200"),
      api.get<Paged<Artifact>>("/learning-artifacts?page_size=200"),
      api.get<Paged<Attribution>>("/attributions?page_size=200"),
      api.get<Paged<EvaluationSuite>>("/evaluation-suites?page_size=200"),
      api.get<Paged<Trial>>("/trials?page_size=200"),
      api.get<TimelineItem[]>("/timeline?limit=200"),
      api.get<Paged<LearningQuestion>>("/learning-questions?page_size=200"),
      api.get<Paged<WeeklyReview>>("/weekly-reviews?page_size=200"),
      api.get<ExpertCandidate[]>("/expert-trajectories/candidates?limit=100"),
      api.get<Paged<ImplicitSignal>>("/implicit-signals?page_size=200"),
    ]);
    employees.value = employeeData.items;
    preferences.value = preferenceData.items;
    interventions.value = interventionData.items;
    artifacts.value = artifactData.items;
    attributions.value = attributionData.items;
    suites.value = suiteData.items;
    trials.value = trialData.items;
    timeline.value = timelineData;
    questions.value = questionData.items;
    reviews.value = reviewData.items;
    candidates.value = candidateData;
    implicitSignals.value = implicitData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

function createPreference(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "写入偏好记忆",
    sub: "偏好记忆实时注入提示词，例如称呼、格式、结论先行。",
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      { name: "key", label: "偏好键", required: true, placeholder: "address_style" },
      {
        name: "value",
        label: "偏好值",
        type: "textarea",
        required: true,
        rows: 3,
        placeholder: "以后称呼我为王哥；结论先行，表格不超过 5 列。",
      },
      {
        name: "scope",
        label: "作用域",
        type: "select",
        options: [
          { value: "personal", label: "个人经验（仅本员工）" },
          { value: "team", label: "团队共享" },
          { value: "organization", label: "组织知识" },
        ],
        value: "personal",
      },
      {
        name: "source",
        label: "来源",
        type: "select",
        options: [
          { value: "real_time", label: "实时对话" },
          { value: "manual", label: "人工配置" },
          { value: "feedback", label: "反馈学习" },
        ],
        value: "real_time",
      },
    ],
    submitLabel: "保存偏好",
    onSubmit: async (values) => {
      await api.post("/preferences", values);
      toast.push("偏好记忆已生效");
      await load();
    },
  });
}

async function forgetPreference(row: Preference): Promise<void> {
  if (!confirm(`确认遗忘偏好「${row.key}」？`)) return;
  try {
    await api.delete(`/preferences/${row.id}`);
    toast.push("偏好记忆已遗忘");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function openIntervention(row: Intervention): void {
  drawer.open(InterventionDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
    onChanged: load,
  });
}

function recordIntervention(): void {
  modal.openForm({
    title: "记录一次单次示范教学",
    sub: "把人工改写记录为接管增量，进入学习流水线。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        numeric: true,
        options: employeeOptions.value,
      },
      { name: "instance_id", label: "任务实例 ID", type: "number", placeholder: "可选" },
      { name: "source_type", label: "来源类型", value: "single_demonstration" },
      { name: "original_output", label: "Agent 原输出（JSON）", type: "json", value: {} },
      { name: "final_output", label: "人工终稿（JSON）", type: "json", value: {} },
      { name: "comment", label: "批注", type: "textarea", rows: 3 },
    ],
    submitLabel: "记录增量",
    onSubmit: async (values) => {
      await api.post("/interventions", {
        ...values,
        employee_id: values.employee_id || null,
        instance_id: values.instance_id || null,
      });
      toast.push("接管增量已记录");
      await load();
    },
  });
}

function openArtifact(row: Artifact): void {
  drawer.open(ArtifactDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
    onChanged: load,
  });
}

function createArtifact(): void {
  modal.openForm({
    title: "新建学习工件",
    sub: "学习工件默认进入审批队列，审批通过后才能生效。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        numeric: true,
        options: employeeOptions.value,
      },
      { name: "attribution", label: "归因", placeholder: "知识缺失 / 规划错误 / 风格不符" },
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
          { value: "personal", label: "个人经验" },
          { value: "team", label: "团队共享" },
          { value: "organization", label: "组织知识" },
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
      await api.post("/learning-artifacts", {
        ...values,
        employee_id: values.employee_id || null,
        evidence,
      });
      toast.push("学习工件已进入审批队列");
      await load();
    },
  });
}

async function quickDecide(row: Artifact, action: "approve" | "reject"): Promise<void> {
  const note = window.prompt(action === "approve" ? "审批备注（可选）" : "驳回原因（可选）") ?? "";
  try {
    await api.post(`/learning-artifacts/${row.id}/${action}`, { note });
    toast.push(action === "approve" ? "已通过" : "已驳回");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "操作失败", "error");
  }
}

function openAttribution(row: Attribution): void {
  drawer.open(AttributionDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
    onChanged: load,
  });
}

function openSuite(row: EvaluationSuite): void {
  drawer.open(EvaluationSuiteDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
    onChanged: load,
  });
}

function openTrial(row: Trial): void {
  drawer.open(TrialDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
  });
}

function openTimeline(row: TimelineItem): void {
  const employeeName = nameOf(row.employee_id);
  if (row.type === "intervention") {
    drawer.open(InterventionDrawer, { id: row.id, employeeName, onChanged: load });
  } else if (row.type === "artifact") {
    drawer.open(ArtifactDrawer, { id: row.id, employeeName, onChanged: load });
  } else if (row.type === "attribution") {
    drawer.open(AttributionDrawer, { id: row.id, employeeName, onChanged: load });
  } else {
    drawer.open(TrialDrawer, { id: row.id, employeeName });
  }
}

function createSuite(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "新建综合评估套件",
    sub: "评估套件用于岗位回归与学习工件的生效门禁。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      { name: "name", label: "名称", required: true, placeholder: "回款话术回归" },
      { name: "code", label: "编码", required: true, placeholder: `suite_${Date.now()}` },
      { name: "threshold", label: "通过阈值", type: "number", value: 0.85, step: 0.01 },
      { name: "regression_tolerance", label: "回归容忍", type: "number", value: 0.02, step: 0.01 },
      {
        name: "enforce_on_activate",
        label: "学习工件生效前强制评估",
        type: "select",
        options: [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ],
        value: "true",
      },
    ],
    submitLabel: "创建套件",
    onSubmit: async (values) => {
      await api.post("/evaluation-suites", {
        ...values,
        enforce_on_activate: String(values.enforce_on_activate) === "true",
      });
      toast.push("评估套件已创建");
      await load();
    },
  });
}

function startTrial(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "发起影子试运行 / 上岗认证",
    sub: "基于员工最近的任务样本计算一次通过率与接管率；认证样本不足会自动失败。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      {
        name: "mode",
        label: "模式",
        type: "select",
        options: [
          { value: "shadow", label: "影子试运行" },
          { value: "certification", label: "上岗资格认证" },
        ],
        value: "certification",
      },
      { name: "sample_size", label: "样本窗口", type: "number", value: 20 },
      { name: "threshold", label: "通过阈值", type: "number", value: 0.85, step: 0.01 },
    ],
    submitLabel: "开始试运行",
    onSubmit: async (values) => {
      const payload = { ...values };
      const employeeId = Number(payload.employee_id);
      delete payload.employee_id;
      const result = await api.post<any>(
        `/digital-employees/${employeeId}/trials`,
        payload,
      );
      toast.push(
        `试运行完成：${result.status} / ${result.decision || "—"}`,
        result.status === "passed" ? "success" : "error",
      );
      await load();
    },
  });
}

function openReview(row: WeeklyReview): void {
  drawer.open(WeeklyReviewDrawer, {
    id: row.id,
    employeeName: nameOf(row.employee_id),
  });
}

function askQuestion(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "记录一次主动提问",
    sub: "提问必须选项化；每日提问次数受员工 active_learning_budget 限制。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      { name: "instance_id", label: "任务实例 ID", type: "number", placeholder: "可选" },
      { name: "question", label: "问题", type: "textarea", required: true, rows: 3 },
      {
        name: "options",
        label: "选项（每行一个，可写 value|label）",
        type: "textarea",
        rows: 3,
        placeholder: "30天|30天\n45天|45天",
      },
      { name: "default_option", label: "默认建议", placeholder: "45天" },
    ],
    submitLabel: "发起提问",
    onSubmit: async (values) => {
      const options = String(values.options || "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const [value, label] = line.split("|").map((item) => item.trim());
          return { value, label: label || value };
        });
      const result = await api.post<any>("/learning-questions", {
        employee_id: values.employee_id,
        instance_id: values.instance_id || null,
        question: values.question,
        options,
        default_option: values.default_option || null,
      });
      toast.push(`提问已记录，今日剩余 ${result.budget.remaining} 次`);
      await load();
    },
  });
}

function answerQuestion(row: LearningQuestion): void {
  const options = (row.options || []).map((item) => ({
    value: String(item.value ?? item.label ?? ""),
    label: String(item.label ?? item.value ?? ""),
  }));
  modal.openForm({
    title: "回答主动提问",
    sub: "回答会生成一条 semantic_memory 学习工件，审批后生效。",
    fields: [
      options.length
        ? {
            name: "answer",
            label: "选择答案",
            type: "select" as const,
            required: true,
            options,
            value: row.options?.[0]?.value ?? "",
          }
        : { name: "answer", label: "答案", required: true },
      { name: "note", label: "补充说明", type: "textarea", rows: 3 },
    ],
    submitLabel: "提交回答",
    onSubmit: async (values) => {
      const result = await api.post<any>(`/learning-questions/${row.id}/answer`, {
        answer: values.answer,
        note: values.note || null,
      });
      toast.push(`回答已入库，学习工件 #${result.artifact.id} 待审批`);
      await load();
    },
  });
}

function generateReview(): void {
  modal.openForm({
    title: "生成成长周报",
    sub: "按最近一周任务、接管、归因与学习工件生成复盘；不选员工则生成租户周报。",
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        options: employeeOptions.value,
      },
      { name: "week_start", label: "周起始日", type: "date" },
    ],
    submitLabel: "生成周报",
    onSubmit: async (values) => {
      const weekStart = values.week_start ? `${values.week_start}T00:00:00Z` : null;
      const result = await api.post<any>("/weekly-reviews/generate", {
        employee_id: values.employee_id || null,
        week_start: weekStart,
      });
      toast.push("周报已生成");
      await load();
      drawer.open(WeeklyReviewDrawer, {
        id: result.id,
        employeeName: nameOf(result.employee_id),
      });
    },
  });
}

function generateReviewBatch(): void {
  modal.openForm({
    title: "批量生成成长周报",
    sub: "为上一自然周有任务的员工各生成一份周报；已存在则跳过。",
    fields: [
      {
        name: "deliver",
        label: "投递方式",
        type: "select",
        options: [
          { value: "no", label: "仅生成，稍后手动投递" },
          { value: "yes", label: "生成后投递到 webhook" },
        ],
        value: "no",
      },
    ],
    submitLabel: "批量生成",
    onSubmit: async (values) => {
      const result = await api.post<any>("/weekly-reviews/generate-batch", {
        deliver: values.deliver === "yes",
      });
      toast.push(`已生成 ${result.generated} 份，跳过 ${result.skipped} 份`);
      await load();
    },
  });
}

function runDailyBatch(): void {
  modal.openForm({
    title: "执行日结学习批量",
    sub: "补归因窗口内未归因的失败任务，并在每日预算内自动发起结构化提问。",
    fields: [
      { name: "lookback_hours", label: "回溯小时", type: "number", value: 24 },
    ],
    submitLabel: "立即执行",
    onSubmit: async (values) => {
      const hours = Math.max(1, Math.min(720, Number(values.lookback_hours) || 24));
      const result = await api.post<any>(
        `/learning/jobs/daily-batch?lookback_hours=${hours}`,
        {},
      );
      toast.push(
        `归因 ${result.attribution?.attributed ?? 0} 条，自动提问 ${result.questions?.created ?? 0} 条`,
      );
      await load();
    },
  });
}

function distillCandidate(row: ExpertCandidate): void {
  modal.openForm({
    title: "蒸馏专家轨迹",
    sub: "把成功轨迹提炼为 procedural_memory 学习工件，进入审批队列。",
    wide: true,
    fields: [
      { name: "name", label: "轨迹名称", value: row.title },
      {
        name: "scope",
        label: "作用域",
        type: "select",
        options: [
          { value: "personal", label: "个人经验" },
          { value: "team", label: "团队共享" },
          { value: "organization", label: "组织知识" },
        ],
        value: "personal",
      },
    ],
    submitLabel: "蒸馏为工件",
    onSubmit: async (values) => {
      const result = await api.post<any>("/expert-trajectories/distill", {
        instance_id: row.instance_id,
        name: values.name,
        scope: values.scope,
      });
      toast.push(`已生成学习工件 #${result.id}，共 ${result.proposal?.steps?.length || 0} 步`);
      await load();
    },
  });
}

function recordImplicitSignal(): void {
  if (!employees.value.length) {
    toast.push("请先创建一个数字员工", "error");
    return;
  }
  modal.openForm({
    title: "记录隐式学习信号",
    sub: "重复追问、换说法、中途放弃、复制片段等，都是低成本学习信号。",
    wide: true,
    fields: [
      {
        name: "employee_id",
        label: "数字员工",
        type: "select",
        required: true,
        numeric: true,
        options: employees.value.map((item) => ({
          value: item.id,
          label: `${item.name} · ${item.code}`,
        })),
      },
      { name: "instance_id", label: "任务实例 ID", type: "number", placeholder: "可选" },
      {
        name: "signal_type",
        label: "信号类型",
        type: "select",
        options: [
          { value: "repeat_question", label: "重复追问" },
          { value: "rephrase", label: "换说法再问" },
          { value: "abandon", label: "中途放弃" },
          { value: "copy_segment", label: "复制片段" },
          { value: "custom", label: "自定义" },
        ],
        value: "repeat_question",
      },
      { name: "content", label: "内容", type: "textarea", rows: 3 },
      { name: "weight", label: "权重", type: "number", value: 1, step: 0.1 },
    ],
    submitLabel: "记录信号",
    onSubmit: async (values) => {
      await api.post("/implicit-signals", {
        employee_id: values.employee_id,
        instance_id: values.instance_id || null,
        signal_type: values.signal_type,
        content: values.content || "",
        weight: Number(values.weight || 1),
      });
      toast.push("隐式信号已记录");
      await load();
    },
  });
}

function primaryAction(): void {
  if (tab.value === "preferences") createPreference();
  else if (tab.value === "interventions") recordIntervention();
  else if (tab.value === "artifacts") createArtifact();
  else if (tab.value === "attributions") load();
  else if (tab.value === "evaluations") createSuite();
  else if (tab.value === "trials") startTrial();
  else if (tab.value === "timeline") load();
  else if (tab.value === "questions") askQuestion();
  else if (tab.value === "reviews") generateReview();
  else if (tab.value === "experts") load();
  else if (tab.value === "implicit") recordImplicitSignal();
}

const actionLabel = computed(() => {
  const labels: Record<TabKey, string> = {
    preferences: "新增偏好",
    interventions: "记录示范",
    artifacts: "新建工件",
    attributions: "刷新列表",
    evaluations: "新建套件",
    trials: "发起试运行",
    timeline: "刷新时间线",
    questions: "发起提问",
    reviews: "生成周报",
    experts: "刷新候选",
    implicit: "记录信号",
  };
  return labels[tab.value];
});

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="learning / continuous loop"
    title="学习中心"
    sub="接管增量、偏好记忆与学习工件审批队列。"
  >
    <template #actions>
      <select v-model="employeeFilter" class="filter-select">
        <option value="">全部员工</option>
        <option v-for="item in employees" :key="item.id" :value="item.id">
          {{ item.name }}
        </option>
      </select>
      <button
        v-if="tab === 'questions'"
        class="btn btn-ghost"
        @click="runDailyBatch"
      >
        <AppIcon name="play" />执行日结
      </button>
      <button
        v-if="tab === 'reviews'"
        class="btn btn-ghost"
        @click="generateReviewBatch"
      >
        <AppIcon name="layers" />批量周报
      </button>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
      <button class="btn btn-primary" @click="primaryAction">
        <AppIcon :name="['attributions', 'timeline', 'experts'].includes(tab) ? 'refresh' : 'plus'" />
        {{ actionLabel }}
      </button>
    </template>
  </PageHeader>

  <div class="tabs">
    <button class="tab" :class="{ active: tab === 'preferences' }" @click="tab = 'preferences'">
      偏好记忆 <span class="dim">{{ filteredPreferences.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'interventions' }" @click="tab = 'interventions'">
      接管增量 <span class="dim">{{ filteredInterventions.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'artifacts' }" @click="tab = 'artifacts'">
      学习工件 <span class="dim">{{ filteredArtifacts.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'attributions' }" @click="tab = 'attributions'">
      失败归因 <span class="dim">{{ filteredAttributions.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'evaluations' }" @click="tab = 'evaluations'">
      评估套件 <span class="dim">{{ filteredSuites.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'trials' }" @click="tab = 'trials'">
      试运行 <span class="dim">{{ filteredTrials.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'timeline' }" @click="tab = 'timeline'">
      调教台 <span class="dim">{{ filteredTimeline.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'questions' }" @click="tab = 'questions'">
      主动提问 <span class="dim">{{ filteredQuestions.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'reviews' }" @click="tab = 'reviews'">
      周复盘 <span class="dim">{{ filteredReviews.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'experts' }" @click="tab = 'experts'">
      专家轨迹 <span class="dim">{{ filteredCandidates.length }}</span>
    </button>
    <button class="tab" :class="{ active: tab === 'implicit' }" @click="tab = 'implicit'">
      隐式信号 <span class="dim">{{ filteredImplicit.length }}</span>
    </button>
  </div>

  <div class="panel">
    <div v-if="loading" class="muted" style="padding: 24px 0">加载中…</div>

    <DataTable
      v-else-if="tab === 'preferences'"
      :rows="filteredPreferences"
      :columns="[
        {
          label: '偏好键',
          format: (row) =>
            `<div class='cell-main'><b class='mono'>${esc(row.key)}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '偏好值', format: (row) => esc(row.value) },
        { label: '作用域', key: 'scope' },
        { label: '来源', format: (row) => `<span class='tag'>${esc(row.source)}</span>` },
        { label: '状态', key: 'status' },
        { label: '更新时间', format: (row) => `<span class='muted'>${fmtDate(row.updated_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有偏好记忆。员工说“以后叫我王哥”时，就应该写进来。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-danger" @click="forgetPreference(row)">遗忘</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'interventions'"
      :rows="filteredInterventions"
      :columns="[
        {
          label: '接管',
          format: (row) =>
            `<div class='cell-main'><b>#${row.id}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '来源', format: (row) => `<span class='tag'>${esc(row.source_type)}</span>` },
        { label: '任务实例', format: (row) => `<span class='mono'>#${row.instance_id ?? '—'}</span>` },
        { label: '变更数', format: (row) => `<b>${row.diff?.length ?? 0}</b>` },
        { label: '状态', key: 'status' },
        { label: '采集时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有接管增量。人工修改 Agent 草稿后，这里会自动采集 diff。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openIntervention(row)">查看 Diff</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'artifacts'"
      :rows="filteredArtifacts"
      :columns="[
        {
          label: '工件',
          format: (row) =>
            `<div class='cell-main'><b>#${row.id}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '目标层', format: (row) => `<span class='mono'>${esc(row.target_layer)}</span>` },
        { label: '归因', format: (row) => esc(row.attribution || '—') },
        { label: '风险', key: 'risk' },
        { label: '作用域', key: 'scope' },
        { label: '版本', format: (row) => `<span class='mono'>v${row.version}</span>` },
        { label: '状态', key: 'status' },
        { label: '', key: 'actions' },
      ]"
      empty-text="审批队列为空。接管增量可以一键提炼为学习工件。"
    >
      <template #cell-risk="{ row }"><StatusPill :status="row.risk" /></template>
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openArtifact(row)">详情</button>
          <button
            v-if="['draft', 'pending_approval'].includes(row.status)"
            class="btn btn-sm btn-primary"
            @click="quickDecide(row, 'approve')"
          >
            通过
          </button>
          <button
            v-if="['draft', 'pending_approval'].includes(row.status)"
            class="btn btn-sm btn-danger"
            @click="quickDecide(row, 'reject')"
          >
            驳回
          </button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'attributions'"
      :rows="filteredAttributions"
      :columns="[
        {
          label: '归因',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.category_label || row.category)}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '置信度', format: (row) => `<span class='mono'>${row.confidence}</span>` },
        { label: '路由动作', format: (row) => `<span class='tag'>${esc(row.routed_action)}</span>` },
        { label: '状态', key: 'status' },
        { label: '任务实例', format: (row) => `<span class='mono'>#${row.instance_id ?? '—'}</span>` },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有归因记录。任务失败或人工接管后会自动归因。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openAttribution(row)">查看</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'evaluations'"
      :rows="filteredSuites"
      :columns="[
        {
          label: '套件',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.name)}</b><small>${esc(nameOf(row.employee_id))} · ${esc(row.code)}</small></div>`,
        },
        { label: '阈值', format: (row) => `<span class='mono'>${row.threshold}</span>` },
        {
          label: '生效前强制',
          format: (row) => `<span class='tag'>${row.enforce_on_activate ? '强制' : '可选'}</span>`,
        },
        { label: '状态', format: (row) => `<span class='tag'>${row.enabled ? '启用' : '停用'}</span>` },
        { label: '创建时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有评估套件。先建一套岗位回归用例，再用它拦住退化。"
    >
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openSuite(row)">详情 / 执行</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'trials'"
      :rows="filteredTrials"
      :columns="[
        {
          label: '试运行',
          format: (row) =>
            `<div class='cell-main'><b>#${row.id}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '模式', format: (row) => `<span class='tag'>${esc(row.mode)}</span>` },
        { label: '状态', key: 'status' },
        { label: '得分', format: (row) => `<b>${row.metrics?.score ?? 0}</b>` },
        { label: '阈值', format: (row) => `<span class='mono'>${row.threshold}</span>` },
        { label: '决策', format: (row) => `<span class='mono'>${esc(row.decision || '—')}</span>` },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有试运行。上岗前先跑一次认证，样本不足会自动失败。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openTrial(row)">详情</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'timeline'"
      :rows="filteredTimeline"
      :columns="[
        {
          label: '事件',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.title)}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '类型', format: (row) => `<span class='tag'>${esc(row.type)}</span>` },
        { label: '类别', format: (row) => `<span class='mono'>${esc(row.category || '—')}</span>` },
        { label: '状态', key: 'status' },
        { label: '摘要', format: (row) => esc(row.summary || '—') },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有学习事件。接管、工件、归因与试运行会汇总到这里。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openTimeline(row)">查看</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'questions'"
      :rows="filteredQuestions"
      :columns="[
        {
          label: '问题',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.question)}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '选项', format: (row) => `<span class='mono'>${(row.options || []).length}</span>` },
        { label: '状态', key: 'status' },
        { label: '回答', format: (row) => esc(row.answer || '—') },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有主动提问。不确定时先问，答案会变成学习工件。"
    >
      <template #cell-status="{ row }"><StatusPill :status="row.status" /></template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button v-if="row.status === 'open'" class="btn btn-sm btn-primary" @click="answerQuestion(row)">
            回答
          </button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'reviews'"
      :rows="filteredReviews"
      :columns="[
        {
          label: '周报',
          format: (row) =>
            `<div class='cell-main'><b>${fmtDate(row.period_start)} 起</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        {
          label: '任务',
          format: (row) => `<span class='mono'>${row.metrics?.total_tasks ?? 0}</span>`,
        },
        {
          label: '一次通过率',
          format: (row) => `<span class='mono'>${row.metrics?.one_pass_rate ?? 0}</span>`,
        },
        {
          label: '接管率',
          format: (row) => `<span class='mono'>${row.metrics?.takeover_rate ?? 0}</span>`,
        },
        { label: '摘要', format: (row) => esc(row.summary || '—') },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有周报。生成一份，看看员工这周学会了什么。"
    >
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm" @click="openReview(row)">查看</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else-if="tab === 'experts'"
      :rows="filteredCandidates"
      :columns="[
        {
          label: '轨迹',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.title)}</b><small>${esc(nameOf(row.employee_id))} · #${row.instance_id}</small></div>`,
        },
        { label: '尝试', format: (row) => `<span class='mono'>${row.attempt}</span>` },
        { label: '步骤', format: (row) => `<span class='mono'>${row.steps}</span>` },
        { label: '接管', format: (row) => `<span class='mono'>${row.takeover}</span>` },
        { label: '质量', format: (row) => `<span class='tag'>${esc(row.quality)}</span>` },
        { label: '完成时间', format: (row) => `<span class='muted'>${fmtDate(row.finished_at)}</span>` },
        { label: '', key: 'actions' },
      ]"
      empty-text="还没有成功轨迹。任务跑成功后，这里会提供可蒸馏的专家样本。"
    >
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn btn-sm btn-primary" @click="distillCandidate(row)">蒸馏</button>
        </div>
      </template>
    </DataTable>

    <DataTable
      v-else
      :rows="filteredImplicit"
      :columns="[
        {
          label: '信号',
          format: (row) =>
            `<div class='cell-main'><b>${esc(row.signal_type)}</b><small>${esc(nameOf(row.employee_id))}</small></div>`,
        },
        { label: '内容', format: (row) => esc(row.content || '—') },
        { label: '权重', format: (row) => `<span class='mono'>${row.weight}</span>` },
        { label: '任务实例', format: (row) => `<span class='mono'>#${row.instance_id ?? '—'}</span>` },
        { label: '时间', format: (row) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
      ]"
      empty-text="还没有隐式信号。重复追问、换说法、放弃、复制片段都可以记录。"
    />
  </div>
</template>

<style scoped>
.filter-select {
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
}
</style>
