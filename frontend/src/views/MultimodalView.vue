<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/api/client";
import type { Paged } from "@/api/types";
import AppIcon from "@/components/AppIcon.vue";
import JsonBlock from "@/components/JsonBlock.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useToastStore } from "@/stores/toast";
import { fmtDate } from "@/utils/format";

interface KnowledgeBase {
  id: number;
  name: string;
}

interface Extraction {
  id: number;
  filename: string;
  kind: string;
  status: string;
  provider: string;
  text: string;
  tables: string[][][];
  meta: Record<string, any>;
  created_at: string;
}

const file = ref<File | null>(null);
const title = ref("");
const knowledgeBaseId = ref("");
const knowledgeBases = ref<KnowledgeBase[]>([]);
const extractions = ref<Extraction[]>([]);
const result = ref<any>(null);
const loading = ref(false);

const toast = useToastStore();

async function load(): Promise<void> {
  try {
    const [baseData, extractionData] = await Promise.all([
      api.get<Paged<KnowledgeBase>>("/knowledge-bases?page_size=200"),
      api.get<Paged<Extraction>>("/multimodal/extractions?page_size=50"),
    ]);
    knowledgeBases.value = baseData.items;
    extractions.value = extractionData.items;
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "加载失败", "error");
  }
}

function pick(event: Event): void {
  const input = event.target as HTMLInputElement;
  file.value = input.files?.[0] || null;
}

async function submit(): Promise<void> {
  if (!file.value) {
    toast.push("请选择文件", "error");
    return;
  }
  loading.value = true;
  try {
    result.value = await api.upload<any>("/multimodal/extract", file.value, {
      title: title.value,
      knowledge_base_id: knowledgeBaseId.value,
    });
    toast.push("解析完成");
    await load();
  } catch (err) {
    toast.push(err instanceof Error ? err.message : "解析失败", "error");
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    eyebrow="knowledge / multimodal"
    title="多模态解析"
    sub="文本、CSV/表格、JSON 本地解析；图片/音频/PDF 需要配置多模态 Provider。"
  >
    <template #actions>
      <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" />刷新</button>
    </template>
  </PageHeader>

  <div class="grid-equal">
    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">上传解析</div>
          <div class="panel-sub">解析结果可同时写入知识库。</div>
        </div>
      </div>
      <div class="field">
        <label>文件</label>
        <input type="file" @change="pick" />
        <span class="help">支持 .txt/.md/.csv/.tsv/.json；图片/音频/PDF 需 Provider。</span>
      </div>
      <div class="field" style="margin-top: 10px">
        <label>标题（写入知识库时使用）</label>
        <input v-model="title" placeholder="合同附件" />
      </div>
      <div class="field" style="margin-top: 10px">
        <label>写入知识库</label>
        <select v-model="knowledgeBaseId">
          <option value="">不写入</option>
          <option v-for="item in knowledgeBases" :key="item.id" :value="String(item.id)">
            {{ item.name }}
          </option>
        </select>
      </div>
      <button class="btn btn-primary" style="margin-top: 14px" :disabled="loading" @click="submit">
        {{ loading ? "解析中…" : "开始解析" }}
      </button>

      <template v-if="result">
        <div class="section-label">解析结果</div>
        <div class="split">
          <span class="tag">{{ result.kind }}</span>
          <span class="tag">{{ result.provider }}</span>
          <span v-if="result.knowledge_document_id" class="tag">
            文档 #{{ result.knowledge_document_id }}
          </span>
        </div>
        <pre class="code" style="max-height: 280px; overflow: auto">{{ result.text }}</pre>
        <template v-if="result.tables?.length">
          <div class="section-label">表格</div>
          <div class="table-wrap">
            <table>
              <tbody>
                <tr v-for="(row, index) in result.tables.slice(0, 20)" :key="index">
                  <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <div class="section-label">元数据</div>
        <JsonBlock :value="result.meta" />
      </template>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">解析记录</div>
          <div class="panel-sub">最近 50 条</div>
        </div>
      </div>
      <div v-if="extractions.length" class="table-wrap">
        <table>
          <thead><tr><th>文件</th><th>类型</th><th>来源</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="item in extractions" :key="item.id">
              <td>{{ item.filename || `#${item.id}` }}</td>
              <td><span class="tag">{{ item.kind }}</span></td>
              <td class="mono">{{ item.provider }}</td>
              <td class="muted">{{ fmtDate(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12px">还没有解析记录。</div>
    </div>
  </div>
</template>
