<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import KnowledgeGraphPanel from "@/components/KnowledgeGraphPanel.vue";
import type { GraphEdge, GraphNode } from "@/components/KnowledgeGraphPanel.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useModalStore } from "@/stores/modal";
import { useToastStore } from "@/stores/toast";
import { esc, fmtDate } from "@/utils/format";

interface KnowledgeBase {
  id: number;
  name: string;
  code: string;
  domain: string;
  description: string;
  status: string;
  created_at: string;
}

interface KnowledgeDocument {
  id: number;
  title: string;
  source?: string | null;
  chunk_count: number;
  created_at: string;
}

interface SearchResult {
  chunk_id: number;
  document_title: string;
  chunk_index: number;
  content: string;
  score: number;
  vector_score: number;
  keyword_score: number;
  embedding_model?: string | null;
}

interface RagEntity {
  name: string;
  type: string;
}

interface RagRelation {
  source_name: string;
  target_name: string;
  type: string;
}

interface RagChunk {
  document_title: string;
  score: number;
  content: string;
}

interface RagResult {
  query: string;
  max_hops: number;
  entities: RagEntity[];
  relations: RagRelation[];
  chunks: RagChunk[];
  context: string;
  answer?: string | null;
  answer_error?: string | null;
  tokens: number;
}

const bases = ref<KnowledgeBase[]>([]);
const selectedId = ref<number | null>(null);
const documents = ref<KnowledgeDocument[]>([]);
const nodes = ref<GraphNode[]>([]);
const edges = ref<GraphEdge[]>([]);
const loading = ref(false);
const baseLoading = ref(false);

const searchQuery = ref("");
const searchMode = ref("auto");
const searchResults = ref<SearchResult[] | null>(null);
const searchLoading = ref(false);

const ragQuery = ref("");
const maxHops = ref(1);
const generateAnswer = ref(true);
const ragResult = ref<RagResult | null>(null);
const ragError = ref("");
const ragLoading = ref(false);

const reindexing = ref(false);

const modal = useModalStore();
const toast = useToastStore();

const selected = computed<KnowledgeBase | null>(
  () => bases.value.find((base) => base.id === selectedId.value) || null,
);

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

async function loadBase(): Promise<void> {
  if (selectedId.value === null) {
    documents.value = [];
    nodes.value = [];
    edges.value = [];
    return;
  }
  baseLoading.value = true;
  try {
    const [documentData, graphData] = await Promise.all([
      api.get<Paged<KnowledgeDocument>>(
        `/knowledge-bases/${selectedId.value}/documents?page_size=100`,
      ),
      api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
        `/knowledge-bases/${selectedId.value}/graph`,
      ),
    ]);
    documents.value = documentData.items;
    nodes.value = graphData.nodes || [];
    edges.value = graphData.edges || [];
  } catch (err) {
    toast.push(errorMessage(err, "知识库详情加载失败"), "error");
  } finally {
    baseLoading.value = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await api.get<Paged<KnowledgeBase>>("/knowledge-bases?page_size=100");
    bases.value = data.items;
    if (!bases.value.length) {
      selectedId.value = null;
      documents.value = [];
      nodes.value = [];
      edges.value = [];
      return;
    }
    if (!bases.value.some((base) => base.id === selectedId.value)) {
      selectedId.value = bases.value[0].id;
    }
    await loadBase();
  } catch (err) {
    toast.push(errorMessage(err, "加载失败"), "error");
  } finally {
    loading.value = false;
  }
}

async function selectBase(id: number): Promise<void> {
  if (selectedId.value === id) return;
  selectedId.value = id;
  searchResults.value = null;
  ragResult.value = null;
  ragError.value = "";
  await loadBase();
}

function openBaseForm(base?: KnowledgeBase): void {
  const editing = Boolean(base);
  modal.openForm({
    title: editing ? "编辑知识库" : "创建知识库",
    sub: editing ? "调整知识域名称、描述与启用状态。" : "创建一个知识域来沉淀业务知识。",
    fields: [
      { name: "name", label: "名称", required: true, placeholder: "产品知识库", value: base?.name || "" },
      {
        name: "code",
        label: "编码",
        required: true,
        placeholder: "product_kb",
        value: base?.code || "",
        help: editing ? "编码创建后不可修改" : "仅支持字母、数字、下划线与连字符",
      },
      {
        name: "domain",
        label: "域",
        type: "select",
        options: ["custom", "platform", "system"],
        value: base?.domain || "custom",
      },
      ...(editing
        ? [
            {
              name: "status",
              label: "状态",
              type: "select" as const,
              options: ["active", "disabled"],
              value: base?.status || "active",
            },
          ]
        : []),
      { name: "description", label: "描述", full: true, type: "textarea", rows: 3, value: base?.description || "" },
    ],
    submitLabel: editing ? "保存" : "创建",
    onSubmit: async (values) => {
      if (base) {
        await api.patch(`/knowledge-bases/${base.id}`, {
          name: values.name,
          domain: values.domain,
          description: values.description,
          status: values.status,
        });
        toast.push("知识库已更新");
      } else {
        const created = await api.post<KnowledgeBase>("/knowledge-bases", values);
        selectedId.value = created.id;
        toast.push("知识库已创建");
      }
      await load();
    },
  });
}

function openDocumentForm(): void {
  if (!selectedId.value) return;
  modal.openForm({
    title: "添加知识文档",
    sub: "内容会按段落自动分块，用于检索。",
    wide: true,
    fields: [
      { name: "title", label: "标题", required: true, placeholder: "退款政策" },
      { name: "source", label: "来源", placeholder: "manual / url / system" },
      { name: "content", label: "正文", type: "textarea", full: true, rows: 10, required: true },
    ],
    submitLabel: "保存并分块",
    onSubmit: async (values) => {
      await api.post(`/knowledge-bases/${selectedId.value}/documents`, values);
      toast.push("文档已写入并完成分块");
      await loadBase();
    },
  });
}

function openTriplesForm(): void {
  if (!selectedId.value) return;
  modal.openForm({
    title: "导入三元组",
    sub: "以 JSON 数组批量写入实体与关系，重复实体会自动复用。",
    wide: true,
    fields: [
      {
        name: "triples",
        label: "三元组 JSON",
        type: "json",
        rows: 12,
        value: [
          {
            source: "退款政策",
            source_type: "policy",
            relation: "属于",
            target: "售后服务",
            target_type: "business",
          },
        ],
        help: "字段：source / source_type / relation / target / target_type",
      },
    ],
    submitLabel: "导入",
    onSubmit: async (values) => {
      const triples = values.triples;
      if (!Array.isArray(triples) || !triples.length) {
        throw new Error("请填写至少一条三元组");
      }
      const result = await api.post<{ created_entities: number; created_relations: number }>(
        `/knowledge-bases/${selectedId.value}/import-triples`,
        { triples },
      );
      toast.push(
        `导入完成：新增 ${result.created_entities} 个实体 / ${result.created_relations} 条关系`,
      );
      await loadBase();
    },
  });
}

async function reindex(): Promise<void> {
  if (!selectedId.value || reindexing.value) return;
  reindexing.value = true;
  try {
    const result = await api.post<{ chunks: number; model: string }>(
      `/knowledge-bases/${selectedId.value}/reindex`,
      {},
    );
    toast.push(`向量重建完成：${result.chunks} 个分块（${result.model}）`);
    await loadBase();
  } catch (err) {
    toast.push(errorMessage(err, "重建失败"), "error");
  } finally {
    reindexing.value = false;
  }
}

async function removeBase(): Promise<void> {
  if (!selected.value) return;
  if (!window.confirm("确认删除整个知识库？文档、分块与图谱都会删除。")) return;
  try {
    await api.delete(`/knowledge-bases/${selected.value.id}`);
    selectedId.value = null;
    toast.push("知识库已删除");
    await load();
  } catch (err) {
    toast.push(errorMessage(err, "删除失败"), "error");
  }
}

async function removeDocument(row: KnowledgeDocument): Promise<void> {
  if (!selectedId.value) return;
  if (!window.confirm("确认删除该文档及其分块？")) return;
  try {
    await api.delete(`/knowledge-bases/${selectedId.value}/documents/${row.id}`);
    toast.push("文档已删除");
    await loadBase();
  } catch (err) {
    toast.push(errorMessage(err, "删除失败"), "error");
  }
}

async function runSearch(): Promise<void> {
  if (!selectedId.value || !searchQuery.value.trim()) return;
  searchLoading.value = true;
  try {
    const result = await api.post<{ results: SearchResult[] }>(
      `/knowledge-bases/${selectedId.value}/search`,
      { query: searchQuery.value, top_k: 5, mode: searchMode.value },
    );
    searchResults.value = result.results || [];
  } catch (err) {
    searchResults.value = [];
    toast.push(errorMessage(err, "检索失败"), "error");
  } finally {
    searchLoading.value = false;
  }
}

async function runRag(): Promise<void> {
  if (!selectedId.value || !ragQuery.value.trim()) return;
  ragLoading.value = true;
  ragError.value = "";
  ragResult.value = null;
  try {
    ragResult.value = await api.post<RagResult>(
      `/knowledge-bases/${selectedId.value}/graph-search`,
      {
        query: ragQuery.value,
        top_k: 5,
        max_hops: maxHops.value,
        answer: generateAnswer.value,
      },
    );
  } catch (err) {
    ragError.value = errorMessage(err, "图谱问答失败");
  } finally {
    ragLoading.value = false;
  }
}

const documentColumns = [
  {
    label: "文档",
    format: (row: KnowledgeDocument) =>
      `<div class='cell-main'><b>${esc(row.title)}</b><small>${esc(row.source || "manual")}</small></div>`,
  },
  { label: "分块", format: (row: KnowledgeDocument) => `<span class='mono'>${row.chunk_count}</span>` },
  { label: "时间", format: (row: KnowledgeDocument) => `<span class='muted'>${fmtDate(row.created_at)}</span>` },
  { label: "", key: "actions" },
];

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="knowledge / bases"
    title="知识库"
    sub="文档分块、关键词检索与知识图谱。"
  >
    <template #actions>
      <button class="btn btn-ghost" :disabled="loading" @click="load">
        <AppIcon name="refresh" />刷新
      </button>
      <button class="btn btn-primary" @click="openBaseForm()"><AppIcon name="plus" />创建知识库</button>
    </template>
  </PageHeader>

  <div v-if="loading" class="skeleton" style="height: 220px" />
  <template v-else>
    <EmptyState
      v-if="!bases.length"
      text="还没有知识库，创建一个来沉淀业务知识。"
    />
    <div v-else class="kb-layout">
      <div class="panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">知识域</div>
            <div class="panel-sub">{{ bases.length }} 个知识库</div>
          </div>
        </div>
        <div class="kb-list">
          <div
            v-for="base in bases"
            :key="base.id"
            class="kb-card"
            :class="{ active: base.id === selectedId }"
            @click="selectBase(base.id)"
          >
            <b>{{ base.name }}</b>
            <small>{{ base.code }} · {{ base.domain }}</small>
          </div>
        </div>
      </div>

      <div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">{{ selected?.name || "知识库" }}</div>
              <div class="panel-sub">
                {{ selected?.description || "无描述" }} · {{ selected?.code || "" }}
              </div>
            </div>
            <div class="row-actions">
              <button class="btn btn-sm" @click="openBaseForm(selected || undefined)">编辑</button>
              <button class="btn btn-sm" @click="openDocumentForm"><AppIcon name="plus" />添加文档</button>
              <button class="btn btn-sm" :disabled="reindexing" @click="reindex">
                {{ reindexing ? "重建中..." : "重建向量" }}
              </button>
              <button class="btn btn-sm" @click="openTriplesForm">导入三元组</button>
              <button class="btn btn-sm btn-danger" @click="removeBase">删除库</button>
            </div>
          </div>
          <div v-if="baseLoading" class="skeleton" style="height: 120px" />
          <DataTable
            v-else
            :rows="documents"
            :columns="documentColumns"
            empty-text="还没有文档"
          >
            <template #cell-actions="{ row }">
              <button class="btn btn-sm btn-ghost" @click="removeDocument(row)">删除</button>
            </template>
          </DataTable>
        </div>

        <div class="panel" style="margin-top: 16px">
          <div class="panel-head">
            <div>
              <div class="panel-title">检索测试</div>
              <div class="panel-sub">关键词 + 中文二元组匹配，返回最相关的分块。</div>
            </div>
          </div>
          <form class="search-row" @submit.prevent="runSearch">
            <input v-model="searchQuery" placeholder="例如：退款政策 7 天" required />
            <select v-model="searchMode" style="max-width: 120px">
              <option value="auto">混合</option>
              <option value="vector">向量</option>
              <option value="keyword">关键词</option>
            </select>
            <button class="btn btn-primary" type="submit" :disabled="searchLoading">
              <AppIcon name="search" />{{ searchLoading ? "检索中..." : "检索" }}
            </button>
          </form>
          <div v-if="searchLoading" class="skeleton" style="height: 90px" />
          <EmptyState
            v-else-if="searchResults === null"
            text="输入问题，查看命中的知识分块。"
          />
          <div v-else-if="searchResults.length" class="result-list">
            <div v-for="item in searchResults" :key="item.chunk_id" class="result-card">
              <div class="head">
                <b>{{ item.document_title || "文档" }}</b>
                <span>
                  {{ item.embedding_model || "keyword" }} · vec {{ item.vector_score ?? 0 }} ·
                  kw {{ item.keyword_score ?? 0 }}
                </span>
              </div>
              <p>{{ item.content }}</p>
            </div>
          </div>
          <EmptyState v-else text="没有命中结果" />
        </div>

        <div class="panel" style="margin-top: 16px">
          <div class="panel-head">
            <div>
              <div class="panel-title">图谱问答（GraphRAG）</div>
              <div class="panel-sub">实体匹配 + 多跳关系 + 分块检索，交给 DeepSeek 生成答案。</div>
            </div>
          </div>
          <form class="search-row" @submit.prevent="runRag">
            <input v-model="ragQuery" placeholder="例如：退款政策属于哪个业务？" required />
            <select v-model.number="maxHops" style="max-width: 100px">
              <option :value="1">1 跳</option>
              <option :value="2">2 跳</option>
              <option :value="3">3 跳</option>
            </select>
            <select v-model="generateAnswer" style="max-width: 120px">
              <option :value="true">生成答案</option>
              <option :value="false">仅上下文</option>
            </select>
            <button class="btn btn-primary" type="submit" :disabled="ragLoading">
              {{ ragLoading ? "检索中..." : "图谱问答" }}
            </button>
          </form>
          <div v-if="ragLoading" class="skeleton" style="height: 120px" />
          <EmptyState v-else-if="!ragResult && !ragError" text="从图谱多跳扩展并回答问题。" />
          <EmptyState v-else-if="ragError" :text="ragError" />
          <div v-else-if="ragResult">
            <div
              v-if="ragResult.answer"
              class="result-card"
              style="border-color: rgba(79, 209, 176, 0.35); background: var(--mint-soft)"
            >
              <div class="head">
                <b>DeepSeek 回答</b>
                <span>{{ ragResult.tokens }} tokens</span>
              </div>
              <p style="font-size: 13px">{{ ragResult.answer }}</p>
            </div>
            <div v-if="ragResult.answer_error" class="alert-banner">
              <div>{{ ragResult.answer_error }}</div>
            </div>

            <div class="section-label">实体</div>
            <div v-if="ragResult.entities.length">
              <span v-for="entity in ragResult.entities" :key="`${entity.name}-${entity.type}`" class="tag" style="margin-right: 6px">
                {{ entity.name }} · {{ entity.type }}
              </span>
            </div>
            <EmptyState v-else text="未匹配到实体" />

            <div class="section-label">关系</div>
            <div v-if="ragResult.relations.length" class="result-list">
              <div v-for="(relation, index) in ragResult.relations" :key="index" class="result-card">
                <div class="head">
                  <b>{{ relation.source_name }} → {{ relation.target_name }}</b>
                  <span>{{ relation.type }}</span>
                </div>
              </div>
            </div>
            <EmptyState v-else text="没有扩展关系" />

            <div class="section-label">知识片段</div>
            <div v-if="ragResult.chunks.length" class="result-list">
              <div v-for="(chunk, index) in ragResult.chunks" :key="index" class="result-card">
                <div class="head">
                  <b>{{ chunk.document_title }}</b>
                  <span>score {{ chunk.score }}</span>
                </div>
                <p>{{ chunk.content }}</p>
              </div>
            </div>
            <EmptyState v-else text="没有命中片段" />
          </div>
        </div>

        <div class="panel" style="margin-top: 16px">
          <div class="panel-head">
            <div>
              <div class="panel-title">知识图谱</div>
              <div class="panel-sub">{{ nodes.length }} 个实体 · {{ edges.length }} 条关系</div>
            </div>
          </div>
          <KnowledgeGraphPanel :nodes="nodes" :edges="edges" />
        </div>
      </div>
    </div>
  </template>
</template>
