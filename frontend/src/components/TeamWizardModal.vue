<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api/client";
import AppIcon from "@/components/AppIcon.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";

interface TemplateRole {
  code?: string;
  name?: string;
  description?: string;
  skills?: string[];
  tools?: string[];
  approval_threshold?: string;
  sandbox?: string;
}

interface TemplateTopology {
  mode?: string;
  edges?: Array<{ from: string; to: string }>;
}

interface TeamTemplateLike {
  id: number;
  name: string;
  description?: string;
  category?: string;
  roles?: TemplateRole[];
  topology?: TemplateTopology;
}

interface MemberDraft {
  key: number;
  role_code: string;
  role_name: string;
  employee_name: string;
  skills: string;
  tools: string;
  approval_threshold: string;
  sandbox: string;
  custom: boolean;
}

const props = defineProps<{
  templates: TeamTemplateLike[];
  initialTemplateId?: number | null;
}>();

const modal = useModalStore();
const toast = useToastStore();
const router = useRouter();

let nextKey = 1;

const selectedId = ref<number>(
  props.initialTemplateId && props.templates.some((item) => item.id === props.initialTemplateId)
    ? props.initialTemplateId
    : props.templates[0]?.id ?? 0,
);
const name = ref("");
const description = ref("");
const members = ref<MemberDraft[]>([]);
const error = ref("");
const submitting = ref(false);

const selectedTemplate = computed<TeamTemplateLike | undefined>(
  () => props.templates.find((item) => item.id === selectedId.value) || props.templates[0],
);

function toDraft(role: TemplateRole, index: number): MemberDraft {
  return {
    key: nextKey++,
    role_code: role.code || `role_${index + 1}`,
    role_name: role.name || role.code || "",
    employee_name: "",
    skills: (role.skills || []).join(", "),
    tools: (role.tools || []).join(", "),
    approval_threshold: role.approval_threshold || "medium",
    sandbox: role.sandbox || "none",
    custom: false,
  };
}

function rebuildMembers(): void {
  members.value = (selectedTemplate.value?.roles || []).map(toDraft);
}

rebuildMembers();
watch(selectedId, rebuildMembers);

interface TopologyLine {
  key: number;
  text: string;
}

const topologyLines = computed<TopologyLine[]>(() => {
  const edges = selectedTemplate.value?.topology?.edges || [];
  const names: Record<string, string> = {};
  for (const member of members.value) {
    names[member.role_code] = member.role_name || member.role_code;
  }
  return edges.map((edge, index) => ({
    key: index,
    text: `${names[edge.from] || edge.from} → ${names[edge.to] || edge.to}`,
  }));
});

function addMember(): void {
  members.value.push({
    key: nextKey++,
    role_code: "custom",
    role_name: "",
    employee_name: "",
    skills: "",
    tools: "",
    approval_threshold: "medium",
    sandbox: "none",
    custom: true,
  });
}

function removeMember(index: number): void {
  members.value.splice(index, 1);
}

function splitList(value: string): string[] {
  return String(value || "")
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function submit(): Promise<void> {
  error.value = "";
  if (!name.value.trim()) {
    error.value = "请填写团队名称";
    return;
  }
  if (!members.value.length) {
    error.value = "至少保留一个角色";
    return;
  }
  submitting.value = true;
  try {
    await api.post("/teams", {
      template_id: selectedId.value,
      name: name.value.trim(),
      description: description.value.trim(),
      members: members.value.map((member) => ({
        role_code: member.role_code,
        role_name: member.role_name || null,
        employee_name: member.employee_name || null,
        skills: splitList(member.skills),
        tools: splitList(member.tools),
        approval_threshold: member.approval_threshold,
        sandbox: member.sandbox,
      })),
      auto_activate: false,
    });
    modal.close();
    toast.push("团队已创建，等待管理员确认");
    router.push("/teams");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="modal" style="width: min(1120px, 96vw)">
    <div class="modal-head">
      <div>
        <h3>从模板创建团队</h3>
        <p>选择模板，自定义成员、技能、工具与审批边界；创建后由管理员确认启用。</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="modal.close()">
        <AppIcon name="close" />
      </button>
    </div>
    <form autocomplete="off" @submit.prevent="submit">
      <div class="modal-body">
        <div class="form-grid">
          <div class="field">
            <label>团队名称</label>
            <input v-model="name" required placeholder="例如：内容审核一队" />
          </div>
          <div class="field">
            <label>团队模板</label>
            <select v-model.number="selectedId">
              <option v-for="template in templates" :key="template.id" :value="template.id">
                {{ template.name }}
              </option>
            </select>
          </div>
          <div class="field full">
            <label>团队说明</label>
            <textarea v-model="description" rows="2" placeholder="这个团队负责什么..." />
          </div>
        </div>

        <div class="section-label">成员与边界（可自定义）</div>
        <div class="member-row-head">
          <span>角色</span>
          <span>员工姓名</span>
          <span>Skills</span>
          <span>工具组</span>
          <span>审批</span>
          <span>沙盒</span>
          <span></span>
        </div>
        <div v-for="(member, index) in members" :key="member.key" class="team-member-row">
          <div class="role-cell">
            <template v-if="member.custom">
              <input v-model="member.role_name" placeholder="角色名" />
            </template>
            <template v-else>
              <b>{{ member.role_name || member.role_code }}</b>
              <small>{{ member.role_code }}</small>
            </template>
          </div>
          <input v-model="member.employee_name" :placeholder="`${member.role_name || '员工'}-${index + 1}`" />
          <input v-model="member.skills" placeholder="skill_a, skill_b" />
          <input v-model="member.tools" placeholder="工具组 A, 工具组 B" />
          <select v-model="member.approval_threshold">
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="dual">双签</option>
          </select>
          <select v-model="member.sandbox">
            <option value="none">无</option>
            <option value="readonly">只读</option>
            <option value="docker">Docker</option>
            <option value="vm">VM</option>
          </select>
          <button class="icon-btn" type="button" title="移除角色" @click="removeMember(index)">
            <AppIcon name="close" />
          </button>
        </div>
        <button class="btn btn-sm" type="button" style="margin-top: 8px" @click="addMember">
          <AppIcon name="plus" />添加角色
        </button>

        <div class="hint-box" style="margin-top: 14px">
          <template v-if="topologyLines.length">
            <b>协作拓扑</b>
            <div v-for="line in topologyLines" :key="line.key">{{ line.text }}</div>
          </template>
          <template v-else>协作拓扑：扁平团队（成员之间无上下级关系）</template>
        </div>

        <div class="form-error" :class="{ show: error }">{{ error }}</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" type="button" @click="modal.close()">取消</button>
        <button class="btn btn-primary" type="submit" :disabled="submitting">
          {{ submitting ? "创建中..." : "创建团队（待确认）" }}
        </button>
      </div>
    </form>
  </div>
</template>
