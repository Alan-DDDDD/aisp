<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import * as api from '../../api/client'

const route = useRoute()
const router = useRouter()

// ── Tabs ────────────────────────────────────────────────────────────
const TABS = [
  { key: 'tasks', label: 'Synthesis Tasks' },
  { key: 'tools', label: 'Generated Tools' },
  { key: 'audit', label: 'Decision Audit' },
]
const activeTab = ref(route.query.tab || 'tasks')

function switchTab(key) {
  activeTab.value = key
  router.push({ query: { tab: key } })
}

// ── 共用 filter ─────────────────────────────────────────────────────
const workspaces = ref([])
const selectedWs = ref('')

// ── Tab 1: Tasks ────────────────────────────────────────────────────
const TASK_STATES = [
  'PENDING', 'SPEC_ENRICHING', 'CODE_GENERATING', 'STATIC_CHECKING',
  'SANDBOX_TESTING', 'AWAITING_APPROVAL', 'AWAITING_HUMAN_RESCUE',
  'REGISTERED', 'DISCARDED', 'FAILED',
]
const taskStateFilter = ref('')
const tasks = ref([])
const taskLoading = ref(false)
const selectedTask = ref(null)
const taskSource = ref(null)
const taskReviews = ref([])
const acting = ref(false)
const actionError = ref('')

async function loadTasks() {
  taskLoading.value = true
  try {
    tasks.value = await api.listSynthesisTasks({
      workspace_id: selectedWs.value,
      state: taskStateFilter.value,
      limit: 100,
    })
  } finally {
    taskLoading.value = false
  }
}

async function openTask(id) {
  selectedTask.value = null
  taskSource.value = null
  taskReviews.value = []
  const [detail, reviews] = await Promise.all([
    api.getSynthesisTask(id),
    api.getSynthesisReviews(id),
  ])
  selectedTask.value = detail
  taskReviews.value = reviews
}

async function loadTaskSource() {
  if (!selectedTask.value || taskSource.value) return
  taskSource.value = await api.getSynthesisSource(selectedTask.value.id)
}

async function approveTask() {
  if (!selectedTask.value) return
  acting.value = true
  actionError.value = ''
  try {
    await api.approveSynthesisTask(selectedTask.value.id)
    await openTask(selectedTask.value.id)
    await loadTasks()
  } catch (e) {
    actionError.value = e.message
  } finally {
    acting.value = false
  }
}

async function rejectTask() {
  if (!selectedTask.value) return
  if (!confirm('確定 reject？task 會被標 DISCARDED。')) return
  acting.value = true
  actionError.value = ''
  try {
    await api.rejectSynthesisTask(selectedTask.value.id)
    await openTask(selectedTask.value.id)
    await loadTasks()
  } catch (e) {
    actionError.value = e.message
  } finally {
    acting.value = false
  }
}

// ── Tab 2: Generated Tools ──────────────────────────────────────────
const toolStatusFilter = ref('active')
const tools = ref([])
const toolLoading = ref(false)

async function loadTools() {
  toolLoading.value = true
  try {
    tools.value = await api.listGeneratedTools({
      workspace_id: selectedWs.value,
      status: toolStatusFilter.value,
      limit: 100,
    })
  } finally {
    toolLoading.value = false
  }
}

async function promote(id) {
  if (!confirm(`Promote ${id} 為全 workspace 可用？`)) return
  await api.promoteGeneratedTool(id)
  await loadTools()
}

async function deprecate(id) {
  if (!confirm(`標 ${id} deprecated？`)) return
  await api.deprecateGeneratedTool(id)
  await loadTools()
}

// ── Tab 3: Decision Audit ───────────────────────────────────────────
const DECISIONS = ['USE', 'COMPOSE', 'GAP']
const ROUTES = ['shortcut_high', 'shortcut_low', 'judge', 'human', 'no_tool_needed']
const decisionFilter = ref('')
const routeFilter = ref('')
const audit = ref([])
const auditLoading = ref(false)
const expandedAuditId = ref(null)

async function loadAudit() {
  auditLoading.value = true
  try {
    audit.value = await api.listDecisionAudit({
      workspace_id: selectedWs.value,
      decision: decisionFilter.value,
      route: routeFilter.value,
      limit: 200,
    })
  } finally {
    auditLoading.value = false
  }
}

// ── 統一載入 / watch ────────────────────────────────────────────────
async function refresh() {
  if (activeTab.value === 'tasks') await loadTasks()
  else if (activeTab.value === 'tools') await loadTools()
  else await loadAudit()
}

watch(activeTab, refresh)
watch(selectedWs, refresh)
watch(taskStateFilter, () => activeTab.value === 'tasks' && loadTasks())
watch(toolStatusFilter, () => activeTab.value === 'tools' && loadTools())
watch(decisionFilter, () => activeTab.value === 'audit' && loadAudit())
watch(routeFilter, () => activeTab.value === 'audit' && loadAudit())

onMounted(async () => {
  workspaces.value = await api.listWorkspaces().catch(() => [])
  await refresh()
})

// ── Badge helpers ───────────────────────────────────────────────────
const STATE_CLASS = {
  AWAITING_APPROVAL: 'bg-blue-100 text-blue-800',
  AWAITING_HUMAN_RESCUE: 'bg-orange-100 text-orange-800',
  REGISTERED: 'bg-emerald-100 text-emerald-800',
  DISCARDED: 'bg-slate-200 text-slate-600',
  FAILED: 'bg-rose-100 text-rose-700',
}
function stateClass(state) {
  return STATE_CLASS[state] || 'bg-amber-100 text-amber-800'
}

const DECISION_CLASS = {
  USE: 'bg-emerald-100 text-emerald-800',
  COMPOSE: 'bg-violet-100 text-violet-800',
  GAP: 'bg-orange-100 text-orange-800',
}

const ROUTE_CLASS = {
  shortcut_high: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  shortcut_low: 'bg-orange-50 text-orange-700 ring-1 ring-orange-200',
  judge: 'bg-blue-50 text-blue-700 ring-1 ring-blue-200',
  human: 'bg-violet-50 text-violet-700 ring-1 ring-violet-200',
  no_tool_needed: 'bg-slate-50 text-slate-600 ring-1 ring-slate-200',
}

function shortDate(s) {
  if (!s) return '-'
  return s.slice(0, 19).replace('T', ' ')
}

function truncate(s, n = 80) {
  if (!s) return ''
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

const canApprove = computed(
  () => selectedTask.value?.state === 'AWAITING_APPROVAL'
)
const canReject = computed(
  () => ['AWAITING_APPROVAL', 'AWAITING_HUMAN_RESCUE'].includes(selectedTask.value?.state)
)
</script>

<template>
  <div class="max-w-7xl mx-auto p-4 sm:p-6">
    <div class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h1 class="text-xl sm:text-2xl font-bold text-slate-800">Self-Extending Agent</h1>
        <p class="text-sm text-slate-500 mt-0.5">
          PLAN §22 — gap detection、tool synthesis、HITL approval 的觀測與管理。
        </p>
      </div>
      <RouterLink to="/admin" class="text-xs text-slate-500 hover:underline shrink-0">
        ← Workspaces
      </RouterLink>
    </div>

    <!-- Tab nav -->
    <div class="border-b border-slate-200 mb-4 flex gap-1 overflow-x-auto">
      <button
        v-for="t in TABS"
        :key="t.key"
        @click="switchTab(t.key)"
        :class="[
          'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition whitespace-nowrap',
          activeTab === t.key
            ? 'border-brand-500 text-brand-600'
            : 'border-transparent text-slate-500 hover:text-slate-700',
        ]"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- Common filters -->
    <div class="flex items-center gap-2 mb-4 flex-wrap text-xs">
      <span class="text-slate-500">Workspace</span>
      <button
        @click="selectedWs = ''"
        :class="['px-2.5 py-1 rounded border', !selectedWs ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200']"
      >全部</button>
      <button
        v-for="ws in workspaces"
        :key="ws.id"
        @click="selectedWs = ws.id"
        :class="['px-2.5 py-1 rounded border', selectedWs === ws.id ? 'text-white border-transparent' : 'bg-white text-slate-700 border-slate-200']"
        :style="selectedWs === ws.id ? { backgroundColor: ws.color } : {}"
      >{{ ws.display_name }}</button>
    </div>

    <!-- ────────────────────────── Tab 1: Tasks ────────────────────────── -->
    <div v-if="activeTab === 'tasks'">
      <div class="flex items-center gap-2 mb-3 flex-wrap text-xs">
        <span class="text-slate-500">State</span>
        <select v-model="taskStateFilter" class="border border-slate-200 rounded px-2 py-1 bg-white">
          <option value="">全部</option>
          <option v-for="s in TASK_STATES" :key="s" :value="s">{{ s }}</option>
        </select>
        <button @click="loadTasks" class="ml-auto text-slate-500 hover:underline">重新載入</button>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-5 gap-3">
        <!-- List -->
        <div class="lg:col-span-2 bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div class="px-3 py-2 text-xs text-slate-500 border-b border-slate-200">
            {{ tasks.length }} 筆
          </div>
          <div v-if="taskLoading" class="p-6 text-sm text-slate-400">載入中…</div>
          <div v-else-if="!tasks.length" class="p-6 text-sm text-slate-400">無資料</div>
          <div v-else class="divide-y divide-slate-100 max-h-[70vh] overflow-y-auto">
            <button
              v-for="t in tasks"
              :key="t.id"
              @click="openTask(t.id)"
              :class="['w-full text-left px-3 py-2.5 hover:bg-slate-50 transition', selectedTask?.id === t.id ? 'bg-brand-50' : '']"
            >
              <div class="flex items-center gap-2 mb-1">
                <span :class="['px-1.5 py-0.5 rounded text-[10px] font-semibold', stateClass(t.state)]">
                  {{ t.state }}
                </span>
                <span class="text-[10px] font-mono text-slate-400">{{ t.workspace_id }}</span>
                <span class="text-[10px] text-slate-400 ml-auto">{{ shortDate(t.created_at) }}</span>
              </div>
              <div class="text-sm font-mono text-slate-700 truncate">{{ t.tool_name }}</div>
              <div class="text-xs text-slate-500 truncate">{{ truncate(t.description, 60) }}</div>
              <div class="text-[10px] text-slate-400 mt-0.5">attempts: {{ t.attempts }}</div>
            </button>
          </div>
        </div>

        <!-- Detail -->
        <div class="lg:col-span-3 bg-white border border-slate-200 rounded-xl p-3 sm:p-4 max-h-[80vh] overflow-y-auto">
          <div v-if="!selectedTask" class="text-sm text-slate-400 text-center py-12">
            從左側挑一筆 task 查看細節
          </div>
          <template v-else>
            <div class="flex items-center gap-2 mb-3">
              <span :class="['px-2 py-0.5 rounded text-xs font-semibold', stateClass(selectedTask.state)]">
                {{ selectedTask.state }}
              </span>
              <span class="text-xs font-mono text-slate-400">{{ selectedTask.id }}</span>
            </div>

            <div class="mb-3">
              <div class="text-sm font-mono text-slate-700">{{ selectedTask.tool_name }}</div>
              <div class="text-sm text-slate-600 mt-1">{{ selectedTask.description }}</div>
            </div>

            <!-- Action bar -->
            <div v-if="canApprove || canReject" class="flex items-center gap-2 mb-4 border border-slate-200 rounded-lg p-2 bg-slate-50">
              <button
                v-if="canApprove"
                @click="approveTask"
                :disabled="acting"
                class="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium disabled:opacity-50"
              >✅ Approve</button>
              <button
                v-if="canReject"
                @click="rejectTask"
                :disabled="acting"
                class="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white text-xs font-medium disabled:opacity-50"
              >❌ Reject</button>
              <span v-if="actionError" class="text-xs text-rose-600">{{ actionError }}</span>
            </div>

            <details class="border border-slate-200 rounded mb-2 text-xs" :open="!!selectedTask.spec">
              <summary class="px-3 py-2 bg-slate-50 cursor-pointer font-semibold">Spec (enriched)</summary>
              <pre class="p-3 font-mono overflow-x-auto bg-white">{{ JSON.stringify(selectedTask.spec, null, 2) }}</pre>
            </details>

            <details class="border border-slate-200 rounded mb-2 text-xs">
              <summary class="px-3 py-2 bg-slate-50 cursor-pointer font-semibold">
                Attempt history ({{ selectedTask.attempt_history?.length || 0 }})
              </summary>
              <div class="p-3 space-y-2">
                <div
                  v-for="(a, i) in selectedTask.attempt_history || []"
                  :key="i"
                  class="border border-slate-100 rounded p-2"
                >
                  <div class="flex items-center gap-2 mb-1">
                    <span class="font-semibold">round {{ a.round }}</span>
                    <span v-if="a.static_ok" class="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">static ok</span>
                    <span v-else class="px-1.5 py-0.5 rounded bg-rose-50 text-rose-700">static fail</span>
                    <span class="px-1.5 py-0.5 rounded bg-slate-50">sandbox: {{ a.sandbox_passed || 0 }} pass / {{ a.sandbox_failed || 0 }} fail</span>
                  </div>
                  <div v-if="a.static_errors?.length" class="font-mono text-rose-600">{{ a.static_errors.join('; ') }}</div>
                  <div v-if="a.sandbox_failure_messages?.length" class="font-mono text-rose-600">
                    {{ a.sandbox_failure_messages.slice(0, 3).join(' | ') }}
                  </div>
                  <div v-if="a.feedback_used" class="text-slate-500 mt-1">feedback: {{ truncate(a.feedback_used, 200) }}</div>
                </div>
              </div>
            </details>

            <details class="border border-slate-200 rounded mb-2 text-xs">
              <summary class="px-3 py-2 bg-slate-50 cursor-pointer font-semibold">
                Behavior observation
              </summary>
              <pre class="p-3 font-mono overflow-x-auto bg-white">{{ JSON.stringify(selectedTask.behavior_observation, null, 2) }}</pre>
            </details>

            <details class="border border-slate-200 rounded mb-2 text-xs" @toggle="loadTaskSource">
              <summary class="px-3 py-2 bg-slate-50 cursor-pointer font-semibold">Source code / tests</summary>
              <div class="p-3 space-y-3">
                <div v-if="!taskSource" class="text-slate-400">展開即載入…</div>
                <template v-else>
                  <div>
                    <div class="text-slate-500 mb-1">code</div>
                    <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto max-h-80">{{ taskSource.code }}</pre>
                  </div>
                  <div>
                    <div class="text-slate-500 mb-1">tests</div>
                    <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto max-h-80">{{ taskSource.tests }}</pre>
                  </div>
                </template>
              </div>
            </details>

            <details v-if="taskReviews.length" class="border border-slate-200 rounded text-xs">
              <summary class="px-3 py-2 bg-slate-50 cursor-pointer font-semibold">
                Review history ({{ taskReviews.length }})
              </summary>
              <div class="divide-y divide-slate-100">
                <div v-for="r in taskReviews" :key="r.id" class="px-3 py-2">
                  <div class="flex items-center gap-2">
                    <span class="font-semibold">{{ r.action }}</span>
                    <span class="font-mono text-slate-500">{{ r.reviewer }}</span>
                    <span class="text-slate-400 ml-auto">{{ shortDate(r.created_at) }}</span>
                  </div>
                  <div v-if="r.hint" class="text-slate-600 mt-1">hint: {{ r.hint }}</div>
                  <div v-if="r.note" class="text-slate-600 mt-1">note: {{ r.note }}</div>
                </div>
              </div>
            </details>
          </template>
        </div>
      </div>
    </div>

    <!-- ────────────────────────── Tab 2: Tools ────────────────────────── -->
    <div v-if="activeTab === 'tools'">
      <div class="flex items-center gap-2 mb-3 flex-wrap text-xs">
        <span class="text-slate-500">Status</span>
        <select v-model="toolStatusFilter" class="border border-slate-200 rounded px-2 py-1 bg-white">
          <option value="active">active</option>
          <option value="deprecated">deprecated</option>
          <option value="">全部</option>
        </select>
        <button @click="loadTools" class="ml-auto text-slate-500 hover:underline">重新載入</button>
      </div>

      <div class="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div v-if="toolLoading" class="p-6 text-sm text-slate-400">載入中…</div>
        <div v-else-if="!tools.length" class="p-6 text-sm text-slate-400">無資料</div>
        <table v-else class="w-full text-sm">
          <thead class="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th class="text-left px-3 py-2">Tool</th>
              <th class="text-left px-3 py-2">Workspace</th>
              <th class="text-left px-3 py-2">Scope</th>
              <th class="text-left px-3 py-2">Side effect</th>
              <th class="text-left px-3 py-2">Approved by</th>
              <th class="text-left px-3 py-2">Approved at</th>
              <th class="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="t in tools" :key="t.id" class="hover:bg-slate-50">
              <td class="px-3 py-2">
                <div class="font-mono text-slate-700">{{ t.id }}</div>
                <div class="text-xs text-slate-500">v{{ t.version }} · {{ truncate(t.description, 70) }}</div>
              </td>
              <td class="px-3 py-2 font-mono text-xs">{{ t.workspace_id || '-' }}</td>
              <td class="px-3 py-2">
                <span :class="['px-1.5 py-0.5 rounded text-xs', t.scope === 'global' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700']">
                  {{ t.scope }}
                </span>
              </td>
              <td class="px-3 py-2 font-mono text-xs">{{ t.side_effect }}</td>
              <td class="px-3 py-2 font-mono text-xs">{{ t.approved_by }}</td>
              <td class="px-3 py-2 text-xs text-slate-500">{{ shortDate(t.approved_at) }}</td>
              <td class="px-3 py-2 text-right whitespace-nowrap">
                <button
                  v-if="t.scope === 'workspace' && t.status === 'active'"
                  @click="promote(t.id)"
                  class="px-2 py-1 rounded bg-violet-50 hover:bg-violet-100 text-violet-700 text-xs mr-1"
                >Promote → global</button>
                <button
                  v-if="t.status === 'active'"
                  @click="deprecate(t.id)"
                  class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs"
                >Deprecate</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ────────────────────────── Tab 3: Audit ────────────────────────── -->
    <div v-if="activeTab === 'audit'">
      <div class="flex items-center gap-2 mb-3 flex-wrap text-xs">
        <span class="text-slate-500">Decision</span>
        <select v-model="decisionFilter" class="border border-slate-200 rounded px-2 py-1 bg-white">
          <option value="">全部</option>
          <option v-for="d in DECISIONS" :key="d" :value="d">{{ d }}</option>
        </select>
        <span class="text-slate-500 ml-2">Route</span>
        <select v-model="routeFilter" class="border border-slate-200 rounded px-2 py-1 bg-white">
          <option value="">全部</option>
          <option v-for="r in ROUTES" :key="r" :value="r">{{ r }}</option>
        </select>
        <button @click="loadAudit" class="ml-auto text-slate-500 hover:underline">重新載入</button>
      </div>

      <div class="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div v-if="auditLoading" class="p-6 text-sm text-slate-400">載入中…</div>
        <div v-else-if="!audit.length" class="p-6 text-sm text-slate-400">無資料</div>
        <div v-else class="divide-y divide-slate-100 max-h-[75vh] overflow-y-auto">
          <div v-for="r in audit" :key="r.id" class="px-3 py-2 hover:bg-slate-50">
            <button
              @click="expandedAuditId = expandedAuditId === r.id ? null : r.id"
              class="w-full text-left"
            >
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span :class="['px-1.5 py-0.5 rounded text-xs font-semibold', DECISION_CLASS[r.decision] || '']">
                  {{ r.decision }}
                </span>
                <span :class="['px-1.5 py-0.5 rounded text-[10px]', ROUTE_CLASS[r.route] || 'bg-slate-50']">
                  {{ r.route }}
                </span>
                <span v-if="r.tool_id" class="font-mono text-xs text-slate-700">{{ r.tool_id }}</span>
                <span v-if="r.gap_spec_name" class="font-mono text-xs text-orange-700">gap: {{ r.gap_spec_name }}</span>
                <span class="text-[10px] text-slate-400 ml-auto">{{ shortDate(r.created_at) }}</span>
              </div>
              <div class="text-sm text-slate-700">{{ r.step_description }}</div>
              <div class="text-xs text-slate-500 mt-0.5">
                ws=<span class="font-mono">{{ r.workspace_id }}</span>
                · conf={{ r.confidence?.toFixed(2) }}
                · max_sim={{ r.max_similarity?.toFixed(2) }}
                <span v-if="r.model_used"> · model={{ r.model_used }}</span>
              </div>
            </button>
            <div v-if="expandedAuditId === r.id" class="mt-2 p-2 bg-slate-50 rounded text-xs space-y-1">
              <div><span class="text-slate-500">query_id:</span> <span class="font-mono">{{ r.query_id }}</span></div>
              <div><span class="text-slate-500">step_id:</span> <span class="font-mono">{{ r.step_id }}</span></div>
              <div v-if="r.compose_chain"><span class="text-slate-500">compose_chain:</span> {{ r.compose_chain.join(' → ') }}</div>
              <div v-if="r.reasoning"><span class="text-slate-500">reasoning:</span> {{ r.reasoning }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
