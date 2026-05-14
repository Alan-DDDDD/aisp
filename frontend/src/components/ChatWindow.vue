<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useChatStore } from '../stores/chat'

const emit = defineEmits(['toggle-trace'])
const store = useChatStore()
const input = ref('')
const listEl = ref(null)

const messages = computed(() => store.messages)

const PROMPT_HINTS = {
  cs: '試試「70 歲可以申請車貸嗎？」或「信貸利率多少？」',
  hr: '試試「我可以休幾天特休？」或「員工健檢有什麼補助？」',
  it: '試試「VPN 連不上怎麼辦？」或「我忘記 AD 密碼了」',
  legal: '試試「NDA 簽署流程？」或「合約審閱要多久？」',
}
const hint = computed(() => PROMPT_HINTS[store.workspaceId] || '輸入訊息開始對話')

watch(
  messages,
  async () => {
    await nextTick()
    if (listEl.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
    }
  },
  { deep: true }
)

function send() {
  const ok = store.sendUserMessage(input.value)
  if (ok) input.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function selectTrace(msg) {
  if (msg.sender_role === 'ai') {
    store.selectTrace(msg.id)
    if (window.matchMedia('(max-width: 1023px)').matches) {
      emit('toggle-trace')
    }
  }
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString('zh-Hant', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div ref="listEl" class="flex-1 overflow-y-auto p-3 sm:p-6 space-y-3">
      <div v-if="messages.length === 0" class="text-center text-slate-400 mt-12">
        <div class="text-sm">
          已切換至「{{ store.currentWorkspace?.display_name || store.workspaceId }}」部門
        </div>
        <div class="text-xs mt-1">{{ hint }}</div>
      </div>

      <div
        v-for="m in messages"
        :key="m.id"
        class="flex"
        :class="m.sender_role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          @click="selectTrace(m)"
          :class="[
            'max-w-[88%] sm:max-w-[80%] rounded-2xl px-3 sm:px-4 py-2 shadow-sm transition',
            m.sender_role === 'user'
              ? 'bg-brand-500 text-white'
              : 'bg-white text-slate-800 border border-slate-200 cursor-pointer hover:border-brand-500',
            store.selectedTraceMessageId === m.id ? 'ring-2 ring-brand-500' : '',
          ]"
        >
          <div class="text-xs opacity-70 mb-1">
            {{ m.sender_role === 'user' ? '你' : 'AI' }} · {{ formatTime(m.created_at) }}
          </div>
          <div class="whitespace-pre-wrap leading-relaxed">{{ m.content }}</div>

          <div
            v-if="m.sender_role === 'ai' && m.extras"
            class="flex flex-wrap gap-1.5 mt-2"
          >
            <span
              v-if="m.extras.ticket && m.extras.ticket.should_create_ticket && m.extras.ticket.ticket_id"
              class="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200"
              :title="m.extras.ticket.rationale"
            >
              工單 {{ m.extras.ticket.ticket_id }}
            </span>
            <span
              v-if="m.extras.risk && m.extras.risk.risk_level"
              :class="[
                'px-2 py-0.5 rounded text-xs font-medium border',
                m.extras.risk.risk_level === 'high'
                  ? 'bg-rose-100 text-rose-800 border-rose-200'
                  : m.extras.risk.risk_level === 'medium'
                  ? 'bg-amber-100 text-amber-800 border-amber-200'
                  : 'bg-emerald-100 text-emerald-800 border-emerald-200',
              ]"
              :title="(m.extras.risk.reasons || []).join('；')"
            >
              風險 {{ m.extras.risk.risk_level }}
            </span>
            <span
              v-if="m.extras.policy && (m.extras.policy.violations || []).length"
              class="px-2 py-0.5 rounded text-xs font-medium bg-rose-100 text-rose-800 border border-rose-200"
              :title="(m.extras.policy.violations || []).join('；')"
            >
              合規警示
            </span>
            <span
              v-else-if="m.extras.policy && m.extras.policy.compliance_note"
              class="px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800 border border-sky-200"
              :title="m.extras.policy.compliance_note"
            >
              合規提示
            </span>
            <span
              v-if="m.extras.tone && m.extras.tone.tone"
              class="px-2 py-0.5 rounded text-xs font-medium bg-violet-100 text-violet-800 border border-violet-200"
              :title="m.extras.tone.rationale"
            >
              語氣 {{ m.extras.tone.tone }}
            </span>
            <span
              v-if="m.extras.clause_analysis && m.extras.clause_analysis.clause_type"
              class="px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800 border border-indigo-200"
              :title="m.extras.clause_analysis.suggestion"
            >
              條款 {{ m.extras.clause_analysis.clause_type }}
            </span>
          </div>

          <div
            v-if="m.sender_role === 'ai' && m.citations && m.citations.length"
            class="mt-3 pt-2 border-t border-slate-100"
          >
            <div class="text-xs text-slate-500 mb-1">知識來源 · {{ m.citations.length }} 筆</div>
            <div class="space-y-1">
              <div
                v-for="(c, i) in m.citations"
                :key="i"
                class="flex items-center gap-2 text-xs"
              >
                <span class="font-mono text-slate-400">[{{ i + 1 }}]</span>
                <span class="flex-1 truncate text-slate-700">{{ c.title || c.source }}</span>
                <span
                  v-if="typeof c.score === 'number'"
                  class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-mono"
                >
                  {{ (c.score * 100).toFixed(0) }}%
                </span>
              </div>
            </div>
          </div>

          <div v-if="m.sender_role === 'ai' && m.trace_id" class="text-xs mt-2 text-brand-600">
            點擊查看 Trace →
          </div>
        </div>
      </div>
    </div>

    <div class="border-t border-slate-200 bg-white p-2 sm:p-3">
      <div class="flex gap-2">
        <textarea
          v-model="input"
          @keydown="onKeydown"
          rows="2"
          placeholder="輸入訊息，Enter 送出（Shift+Enter 換行）"
          class="flex-1 resize-none border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        ></textarea>
        <button
          @click="send"
          class="bg-brand-500 hover:bg-brand-600 text-white px-3 sm:px-4 rounded-lg font-medium transition shrink-0"
        >
          送出
        </button>
      </div>
      <div class="flex items-center gap-2 sm:gap-3 mt-2 text-xs text-slate-500 flex-wrap">
        <span
          class="inline-block w-2 h-2 rounded-full"
          :class="{
            'bg-emerald-500': store.connectionStatus === 'open',
            'bg-amber-400': ['connecting', 'closed'].includes(store.connectionStatus),
            'bg-rose-500': store.connectionStatus === 'error',
            'bg-slate-300': store.connectionStatus === 'idle',
          }"
        ></span>
        <span class="truncate">WebSocket: {{ store.connectionStatus }}</span>
        <button
          @click="emit('toggle-trace')"
          class="lg:hidden ml-auto px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium"
        >Trace ▸</button>
        <span class="hidden lg:inline lg:ml-auto truncate">Room: {{ store.roomId || '—' }}</span>
      </div>
    </div>
  </div>
</template>
