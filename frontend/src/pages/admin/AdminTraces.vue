<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import * as api from '../../api/client'

const route = useRoute()
const router = useRouter()

const traces = ref([])
const workspaces = ref([])
const selectedWs = ref(route.query.workspace_id || '')
const selectedTrace = ref(null)
const loadingList = ref(true)
const loadingDetail = ref(false)
const error = ref(null)

async function loadList() {
  loadingList.value = true
  error.value = null
  try {
    traces.value = await api.listTraces(
      selectedWs.value ? { workspace_id: selectedWs.value, limit: 50 } : { limit: 50 }
    )
  } catch (e) {
    error.value = e.message
  } finally {
    loadingList.value = false
  }
}

async function loadTraceDetail(id) {
  if (!id) {
    selectedTrace.value = null
    return
  }
  loadingDetail.value = true
  try {
    selectedTrace.value = await api.getTrace(id)
  } catch (e) {
    selectedTrace.value = { error: e.message }
  } finally {
    loadingDetail.value = false
  }
}

function selectTrace(id) {
  router.push({ query: { ...route.query, id } })
}

function pickWorkspace(id) {
  selectedWs.value = id
  router.push({ query: { ...route.query, workspace_id: id || undefined, id: undefined } })
  selectedTrace.value = null
  loadList()
}

onMounted(async () => {
  workspaces.value = await api.listWorkspaces().catch(() => [])
  await loadList()
  if (route.query.id) await loadTraceDetail(route.query.id)
})

watch(() => route.query.id, (id) => loadTraceDetail(id))

const stepTotal = computed(() => selectedTrace.value?.steps?.length || 0)
</script>

<template>
  <div class="max-w-7xl mx-auto p-6">
    <div class="mb-4 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-slate-800">Trace Explorer</h1>
      <RouterLink to="/admin" class="text-xs text-slate-500 hover:underline">← Workspaces</RouterLink>
    </div>

    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <span class="text-xs text-slate-500">過濾</span>
      <button
        @click="pickWorkspace('')"
        :class="['px-2.5 py-1 rounded text-xs border', !selectedWs ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200']"
      >全部</button>
      <button
        v-for="ws in workspaces"
        :key="ws.id"
        @click="pickWorkspace(ws.id)"
        :class="['px-2.5 py-1 rounded text-xs border', selectedWs === ws.id ? 'text-white border-transparent' : 'bg-white text-slate-700 border-slate-200']"
        :style="selectedWs === ws.id ? { backgroundColor: ws.color } : {}"
      >{{ ws.display_name }}</button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">
      <!-- List -->
      <div class="lg:col-span-2 bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div class="px-3 py-2 text-xs text-slate-500 border-b border-slate-200 flex items-center justify-between">
          <span>最近 {{ traces.length }} 筆</span>
          <button @click="loadList" class="hover:underline">重新載入</button>
        </div>
        <div v-if="loadingList" class="p-6 text-sm text-slate-400">載入中…</div>
        <div v-else-if="error" class="p-6 text-sm text-rose-600">{{ error }}</div>
        <div v-else-if="!traces.length" class="p-6 text-sm text-slate-400">無 trace</div>
        <div v-else class="divide-y divide-slate-100 max-h-[70vh] overflow-y-auto">
          <button
            v-for="t in traces"
            :key="t.id"
            @click="selectTrace(t.id)"
            :class="['w-full text-left px-3 py-2.5 hover:bg-slate-50 transition', $route.query.id === t.id ? 'bg-brand-50' : '']"
          >
            <div class="flex items-center gap-2 text-[10px] font-mono text-slate-400 mb-0.5">
              <span class="px-1 rounded bg-slate-100 text-slate-600">{{ t.workspace_id || '-' }}</span>
              <span>{{ t.workflow_id }}</span>
              <span class="ml-auto">{{ t.total_latency_ms }}ms · {{ t.step_count }} steps</span>
            </div>
            <div class="text-sm text-slate-700 line-clamp-2">{{ t.preview || '(no preview)' }}</div>
          </button>
        </div>
      </div>

      <!-- Detail -->
      <div class="lg:col-span-3 bg-white border border-slate-200 rounded-xl p-4">
        <div v-if="!$route.query.id" class="text-sm text-slate-400 text-center py-12">
          從左側挑一筆 trace 查看 pipeline
        </div>
        <div v-else-if="loadingDetail" class="text-sm text-slate-400">載入中…</div>
        <div v-else-if="selectedTrace?.error" class="text-sm text-rose-600">{{ selectedTrace.error }}</div>
        <template v-else-if="selectedTrace">
          <div class="text-xs text-slate-500 mb-3 space-y-0.5">
            <div>Workflow: <span class="font-mono text-slate-700">{{ selectedTrace.workflow_id }}</span></div>
            <div>Trace ID: <span class="font-mono text-slate-700 break-all">{{ selectedTrace.id }}</span></div>
            <div>Total: <span class="font-semibold text-slate-700">{{ selectedTrace.total_latency_ms }}ms</span> · {{ stepTotal }} steps</div>
          </div>

          <details
            v-for="(step, i) in selectedTrace.steps"
            :key="i"
            class="border border-slate-200 rounded-lg overflow-hidden mb-2"
            :open="i === 0"
          >
            <summary class="px-3 py-2 bg-slate-50 cursor-pointer flex items-center justify-between text-sm hover:bg-slate-100">
              <div class="flex items-center gap-2">
                <span class="font-mono text-xs text-slate-500">{{ i + 1 }}.</span>
                <span class="font-semibold">{{ step.agent_id }}</span>
                <span class="text-xs text-slate-500">({{ step.step_id }})</span>
                <span v-if="step.error" class="text-rose-500 text-xs">errored</span>
              </div>
              <span class="text-xs text-slate-500">{{ step.latency_ms }}ms</span>
            </summary>
            <div class="p-3 space-y-2 text-xs">
              <div>
                <div class="text-slate-500 mb-1">Input</div>
                <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto">{{ JSON.stringify(step.input, null, 2) }}</pre>
              </div>
              <div v-if="step.output">
                <div class="text-slate-500 mb-1">Output</div>
                <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto">{{ JSON.stringify(step.output, null, 2) }}</pre>
              </div>
              <div v-if="step.error">
                <div class="text-rose-500 mb-1">Error</div>
                <pre class="bg-rose-50 text-rose-700 p-2 rounded font-mono overflow-x-auto">{{ step.error }}</pre>
              </div>
            </div>
          </details>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
