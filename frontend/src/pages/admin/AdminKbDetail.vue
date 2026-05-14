<script setup>
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import * as api from '../../api/client'

const props = defineProps({ id: String })

const docs = ref([])
const chunksByDoc = ref({})
const loadingChunks = ref({})
const loading = ref(true)
const error = ref(null)

const showAdd = ref(false)
const submitting = ref(false)
const addError = ref(null)
const mode = ref('text')  // 'text' | 'pdf'
const form = ref({ title: '', content: '', source_type: 'manual', category: '' })
const pdfFile = ref(null)
const pdfInputRef = ref(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    docs.value = await api.listKbDocuments(props.id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function toggleChunks(doc) {
  if (chunksByDoc.value[doc.id]) {
    chunksByDoc.value[doc.id] = null
    return
  }
  loadingChunks.value[doc.id] = true
  try {
    chunksByDoc.value[doc.id] = await api.listKbChunks(doc.id)
  } finally {
    loadingChunks.value[doc.id] = false
  }
}

function resetForm() {
  form.value = { title: '', content: '', source_type: 'manual', category: '' }
  pdfFile.value = null
  if (pdfInputRef.value) pdfInputRef.value.value = ''
  addError.value = null
}

function openAdd() {
  resetForm()
  mode.value = 'text'
  showAdd.value = true
}

function cancelAdd() {
  showAdd.value = false
  resetForm()
}

function onPdfPicked(e) {
  const f = e.target.files?.[0] || null
  pdfFile.value = f
}

async function submitAdd() {
  if (mode.value === 'text') {
    if (!form.value.title.trim() || !form.value.content.trim()) {
      addError.value = '標題與內容皆為必填'
      return
    }
  } else {
    if (!pdfFile.value) {
      addError.value = '請選擇 PDF 檔案'
      return
    }
  }
  submitting.value = true
  addError.value = null
  try {
    if (mode.value === 'text') {
      const metadata = form.value.category.trim()
        ? { category: form.value.category.trim() }
        : {}
      await api.ingestKbDocument(props.id, {
        title: form.value.title.trim(),
        content: form.value.content,
        source_type: form.value.source_type.trim() || 'manual',
        metadata,
      })
    } else {
      await api.uploadKbPdf(props.id, pdfFile.value, {
        title: form.value.title.trim() || undefined,
        category: form.value.category.trim() || undefined,
      })
    }
    showAdd.value = false
    resetForm()
    await load()
  } catch (e) {
    addError.value = e.message
  } finally {
    submitting.value = false
  }
}

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div class="max-w-6xl mx-auto p-4 sm:p-6 space-y-4">
    <div>
      <RouterLink to="/admin" class="text-xs text-slate-500 hover:underline">← Workspaces</RouterLink>
    </div>

    <div class="flex items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="text-xl sm:text-2xl font-bold text-slate-800">Knowledge Base</h1>
        <p class="text-sm text-slate-500 truncate">KB ID <span class="font-mono">{{ id }}</span></p>
      </div>
      <button
        v-if="!showAdd"
        @click="openAdd"
        class="text-xs px-3 py-1.5 rounded bg-brand-600 hover:bg-brand-700 text-white font-medium shrink-0"
      >+ 新增文件</button>
    </div>

    <div
      v-if="showAdd"
      class="bg-white border border-brand-200 rounded-xl p-4 sm:p-5 space-y-3"
    >
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-slate-800">新增文件</h2>
        <button
          @click="cancelAdd"
          class="text-xs text-slate-500 hover:text-slate-700"
        >取消</button>
      </div>

      <div class="flex gap-1 border-b border-slate-200">
        <button
          @click="mode = 'text'"
          :class="[
            'px-3 py-1.5 text-xs font-medium border-b-2 -mb-px',
            mode === 'text'
              ? 'border-brand-500 text-brand-700'
              : 'border-transparent text-slate-500 hover:text-slate-700',
          ]"
        >貼文字</button>
        <button
          @click="mode = 'pdf'"
          :class="[
            'px-3 py-1.5 text-xs font-medium border-b-2 -mb-px',
            mode === 'pdf'
              ? 'border-brand-500 text-brand-700'
              : 'border-transparent text-slate-500 hover:text-slate-700',
          ]"
        >上傳 PDF</button>
      </div>

      <div v-if="mode === 'text'" class="space-y-2">
        <label class="block">
          <span class="text-xs text-slate-600">標題</span>
          <input
            v-model="form.title"
            type="text"
            :disabled="submitting"
            placeholder="例：車貸申請年齡上限"
            class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:border-brand-500"
          />
        </label>

        <label class="block">
          <span class="text-xs text-slate-600">內容</span>
          <textarea
            v-model="form.content"
            :disabled="submitting"
            rows="6"
            placeholder="文件全文。FAQ 可寫 Q/A 兩段，runtime 會自動切 chunks。"
            class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm font-mono focus:outline-none focus:border-brand-500"
          ></textarea>
        </label>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label class="block">
            <span class="text-xs text-slate-600">source_type</span>
            <input
              v-model="form.source_type"
              type="text"
              :disabled="submitting"
              class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm font-mono focus:outline-none focus:border-brand-500"
            />
          </label>
          <label class="block">
            <span class="text-xs text-slate-600">category（選填）</span>
            <input
              v-model="form.category"
              type="text"
              :disabled="submitting"
              placeholder="如：loan / policy"
              class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm font-mono focus:outline-none focus:border-brand-500"
            />
          </label>
        </div>
      </div>

      <div v-else class="space-y-2">
        <label class="block">
          <span class="text-xs text-slate-600">PDF 檔案</span>
          <input
            ref="pdfInputRef"
            type="file"
            accept=".pdf,application/pdf"
            :disabled="submitting"
            @change="onPdfPicked"
            class="mt-1 w-full text-sm file:mr-3 file:px-3 file:py-1.5 file:rounded file:border-0 file:bg-brand-50 file:text-brand-700 file:text-xs hover:file:bg-brand-100"
          />
          <span v-if="pdfFile" class="text-[10px] text-slate-500 font-mono block mt-1">
            {{ pdfFile.name }} · {{ (pdfFile.size / 1024).toFixed(1) }} KB
          </span>
          <span class="text-[10px] text-slate-400 block mt-1">
            上限 20 MB；純圖片掃描檔需先 OCR 才能上傳
          </span>
        </label>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label class="block">
            <span class="text-xs text-slate-600">標題（選填，預設用檔名）</span>
            <input
              v-model="form.title"
              type="text"
              :disabled="submitting"
              placeholder="例：員工手冊 v2.3"
              class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:border-brand-500"
            />
          </label>
          <label class="block">
            <span class="text-xs text-slate-600">category（選填）</span>
            <input
              v-model="form.category"
              type="text"
              :disabled="submitting"
              placeholder="如：policy / sop"
              class="mt-1 w-full px-3 py-2 border border-slate-300 rounded text-sm font-mono focus:outline-none focus:border-brand-500"
            />
          </label>
        </div>
      </div>

      <div v-if="addError" class="text-xs text-rose-600">{{ addError }}</div>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button
          @click="cancelAdd"
          :disabled="submitting"
          class="text-xs px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700"
        >取消</button>
        <button
          @click="submitAdd"
          :disabled="submitting"
          class="text-xs px-3 py-1.5 rounded bg-brand-600 hover:bg-brand-700 disabled:bg-brand-300 text-white font-medium"
        >{{ submitting ? (mode === 'pdf' ? '解析 PDF 中…' : '送出中…') : '儲存' }}</button>
      </div>
    </div>

    <div v-if="loading" class="text-slate-400 text-sm">載入中…</div>
    <div v-else-if="error" class="text-rose-600 text-sm">{{ error }}</div>

    <div v-else class="space-y-2">
      <div
        v-for="doc in docs"
        :key="doc.id"
        class="bg-white border border-slate-200 rounded-lg"
      >
        <button
          @click="toggleChunks(doc)"
          class="w-full text-left p-4 hover:bg-slate-50 transition"
        >
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="font-medium text-slate-800 truncate">{{ doc.title }}</div>
              <div class="text-xs text-slate-500 mt-0.5 flex items-center gap-3 flex-wrap">
                <span><span class="font-mono">{{ doc.source_type }}</span></span>
                <span>{{ doc.chunk_count }} chunks</span>
                <span v-if="doc.metadata?.category">
                  category: <span class="font-mono">{{ doc.metadata.category }}</span>
                </span>
                <span v-if="doc.metadata?.subcategory">
                  / <span class="font-mono">{{ doc.metadata.subcategory }}</span>
                </span>
                <span v-if="doc.metadata?.original_filename" class="text-slate-400">
                  · <span class="font-mono">{{ doc.metadata.original_filename }}</span>
                </span>
              </div>
            </div>
            <div class="text-xs text-slate-400 shrink-0">
              {{ chunksByDoc[doc.id] ? '收起' : '展開' }}
            </div>
          </div>
        </button>

        <div v-if="loadingChunks[doc.id]" class="px-4 pb-4 text-xs text-slate-400">載入 chunks…</div>
        <div v-else-if="chunksByDoc[doc.id]" class="px-4 pb-4 space-y-2">
          <div
            v-for="(c, i) in chunksByDoc[doc.id]"
            :key="c.id"
            class="border-l-2 border-brand-200 pl-3 py-1"
          >
            <div class="text-[10px] text-slate-400 font-mono mb-0.5">chunk #{{ c.chunk_index }} · {{ c.id.slice(0, 8) }}</div>
            <div class="text-sm text-slate-700 whitespace-pre-wrap">{{ c.text }}</div>
          </div>
        </div>
      </div>

      <div v-if="!docs.length" class="text-sm text-slate-400 text-center py-12">
        此 KB 暫無文件
      </div>
    </div>
  </div>
</template>
