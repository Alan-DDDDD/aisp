<script setup>
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const emit = defineEmits(['close'])
const store = useChatStore()
const trace = computed(() => store.selectedTrace)

function formatJson(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<template>
  <aside class="w-full h-full border-l border-slate-200 bg-white flex flex-col">
    <div class="px-4 py-3 border-b border-slate-200 flex items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="text-sm font-semibold text-slate-800">AI Pipeline Trace</div>
        <div class="text-xs text-slate-500 mt-0.5">
          點選聊天窗的 AI 訊息來檢視該次 pipeline
        </div>
      </div>
      <button
        @click="emit('close')"
        class="lg:hidden text-slate-400 hover:text-slate-700 shrink-0 text-2xl leading-none px-2 -mr-1"
        aria-label="關閉 Trace 面板"
      >×</button>
    </div>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="!trace" class="text-sm text-slate-400 text-center mt-12">
        尚未選取任何 trace。
      </div>

      <div v-else class="space-y-3">
        <div class="text-xs text-slate-500 mb-2">
          <div>Workflow: <span class="font-mono">{{ trace.workflow_id }}</span></div>
          <div>Trace ID: <span class="font-mono break-all">{{ trace.id }}</span></div>
          <div>Total: <span class="font-semibold">{{ trace.total_latency_ms }}ms</span></div>
        </div>

        <details
          v-for="(step, i) in trace.steps"
          :key="i"
          class="border border-slate-200 rounded-lg overflow-hidden"
          :open="i === 0"
        >
          <summary
            class="px-3 py-2 bg-slate-50 cursor-pointer flex items-center justify-between text-sm hover:bg-slate-100"
          >
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
              <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto">{{ formatJson(step.input) }}</pre>
            </div>
            <div v-if="step.output">
              <div class="text-slate-500 mb-1">Output</div>
              <pre class="bg-slate-50 p-2 rounded font-mono overflow-x-auto">{{ formatJson(step.output) }}</pre>
            </div>
            <div v-if="step.error">
              <div class="text-rose-500 mb-1">Error</div>
              <pre class="bg-rose-50 text-rose-700 p-2 rounded font-mono overflow-x-auto">{{ step.error }}</pre>
            </div>
          </div>
        </details>
      </div>
    </div>
  </aside>
</template>
