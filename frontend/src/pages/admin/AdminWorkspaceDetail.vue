<script setup>
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import * as api from '../../api/client'

const route = useRoute()
const router = useRouter()
const props = defineProps({ id: String })

const workspace = ref(null)
const workflowYaml = ref('')
const traces = ref([])
const tickets = ref([])
const loading = ref(true)
const error = ref(null)
const reloadStatus = ref(null)

async function load() {
  loading.value = true
  error.value = null
  reloadStatus.value = null
  try {
    const [ws, yaml, t, tk] = await Promise.all([
      api.getAdminWorkspace(props.id),
      api.getWorkflowYaml(props.id).catch(() => '(workflow.yaml 不存在或解析失敗)'),
      api.listTraces({ workspace_id: props.id, limit: 10 }),
      api.listTickets(props.id),
    ])
    workspace.value = ws
    workflowYaml.value = yaml
    traces.value = t
    tickets.value = tk
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function doReload() {
  try {
    const r = await api.reloadWorkflow(props.id)
    reloadStatus.value = `已重新載入 workflow ${r.workflow_id} (${r.step_count} steps)`
    workflowYaml.value = await api.getWorkflowYaml(props.id)
  } catch (e) {
    reloadStatus.value = `Reload 失敗：${e.message}`
  }
}

onMounted(load)
watch(() => props.id, load)

const workflowSteps = (yaml) => {
  // 從 yaml 文字裡簡易提取 step ids（不做嚴格 yaml parse）
  const matches = [...yaml.matchAll(/^- id:\s*([\w-]+)/gm)]
  return matches.map((m) => m[1])
}
</script>

<template>
  <div class="max-w-6xl mx-auto p-6 space-y-6">
    <div>
      <RouterLink to="/admin" class="text-xs text-slate-500 hover:underline">← Workspaces</RouterLink>
    </div>

    <div v-if="loading" class="text-slate-400 text-sm">載入中…</div>
    <div v-else-if="error" class="text-rose-600 text-sm">{{ error }}</div>

    <template v-else-if="workspace">
      <div class="flex items-center gap-4">
        <div
          class="w-14 h-14 rounded-xl flex items-center justify-center text-white font-bold text-lg shrink-0"
          :style="{ backgroundColor: workspace.color }"
        >
          {{ workspace.icon || workspace.id.slice(0, 2).toUpperCase() }}
        </div>
        <div class="min-w-0">
          <h1 class="text-2xl font-bold text-slate-800">{{ workspace.display_name }}</h1>
          <p class="text-sm text-slate-500 mt-0.5">{{ workspace.description }}</p>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Workflow -->
        <section class="bg-white border border-slate-200 rounded-xl p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="font-semibold text-slate-800">Workflow</h2>
            <button
              @click="doReload"
              class="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700"
            >Reload from YAML</button>
          </div>
          <div v-if="reloadStatus" class="text-xs text-emerald-600 mb-2">{{ reloadStatus }}</div>

          <div class="flex items-center gap-1 flex-wrap mb-3">
            <template v-for="(sid, i) in workflowSteps(workflowYaml)" :key="sid">
              <span class="px-2 py-1 rounded bg-brand-100 text-brand-700 text-xs font-mono">{{ sid }}</span>
              <span
                v-if="i < workflowSteps(workflowYaml).length - 1"
                class="text-slate-300 text-xs"
              >→</span>
            </template>
          </div>

          <details class="text-xs">
            <summary class="cursor-pointer text-slate-500 hover:text-slate-700 mb-2">完整 YAML</summary>
            <pre class="bg-slate-50 p-3 rounded font-mono overflow-x-auto text-slate-700">{{ workflowYaml }}</pre>
          </details>
        </section>

        <!-- Knowledge Bases -->
        <section class="bg-white border border-slate-200 rounded-xl p-5">
          <h2 class="font-semibold text-slate-800 mb-3">Knowledge Bases</h2>
          <div v-if="!workspace.kbs.length" class="text-sm text-slate-400">尚無 KB</div>
          <div v-else class="space-y-2">
            <RouterLink
              v-for="kb in workspace.kbs"
              :key="kb.id"
              :to="`/admin/kbs/${kb.id}`"
              class="flex items-center justify-between p-3 rounded border border-slate-200 hover:border-slate-300 hover:bg-slate-50 transition"
            >
              <div>
                <div class="font-mono text-sm text-slate-700">{{ kb.name }}</div>
                <div class="text-xs text-slate-500 mt-0.5">
                  collection: <span class="font-mono">{{ kb.collection_name }}</span>
                </div>
              </div>
              <div class="text-right">
                <div class="text-sm font-semibold text-slate-700">{{ kb.doc_count }}</div>
                <div class="text-xs text-slate-500">documents</div>
              </div>
            </RouterLink>
          </div>
        </section>

        <!-- Recent Traces -->
        <section class="bg-white border border-slate-200 rounded-xl p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="font-semibold text-slate-800">Recent Traces</h2>
            <RouterLink to="/admin/traces" class="text-xs text-brand-600 hover:underline">全部 →</RouterLink>
          </div>
          <div v-if="!traces.length" class="text-sm text-slate-400">尚無 trace</div>
          <div v-else class="space-y-1">
            <RouterLink
              v-for="t in traces"
              :key="t.id"
              :to="`/admin/traces?id=${t.id}`"
              class="block p-2 rounded hover:bg-slate-50 transition"
            >
              <div class="text-xs text-slate-700 truncate">{{ t.preview || '(no preview)' }}</div>
              <div class="text-[10px] text-slate-400 font-mono mt-0.5">
                {{ t.workflow_id }} · {{ t.step_count }} steps · {{ t.total_latency_ms }}ms
              </div>
            </RouterLink>
          </div>
        </section>

        <!-- Tickets -->
        <section class="bg-white border border-slate-200 rounded-xl p-5">
          <h2 class="font-semibold text-slate-800 mb-3">Tickets</h2>
          <div v-if="!tickets.length" class="text-sm text-slate-400">尚無 ticket</div>
          <div v-else class="space-y-2">
            <div
              v-for="t in tickets"
              :key="t.id"
              class="p-3 rounded border border-slate-200"
            >
              <div class="flex items-center gap-2 text-xs">
                <span class="font-mono font-semibold text-amber-700">{{ t.id }}</span>
                <span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-[10px]">{{ t.status }}</span>
              </div>
              <div class="text-sm text-slate-700 mt-1">{{ t.summary }}</div>
              <div v-if="t.rationale" class="text-xs text-slate-500 mt-1">{{ t.rationale }}</div>
            </div>
          </div>
        </section>
      </div>
    </template>
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
