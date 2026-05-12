<script setup>
import { useChatStore } from '../stores/chat'

const store = useChatStore()

async function pick(id) {
  if (id === store.workspaceId) return
  await store.switchWorkspace(id)
}
</script>

<template>
  <div class="flex items-center gap-2">
    <span class="text-xs text-slate-500 mr-1">部門</span>
    <button
      v-for="ws in store.workspaces"
      :key="ws.id"
      @click="pick(ws.id)"
      :class="[
        'px-3 py-1.5 rounded-lg text-sm font-medium transition flex items-center gap-2 border',
        store.workspaceId === ws.id
          ? 'text-white border-transparent shadow-sm'
          : 'bg-white text-slate-700 border-slate-200 hover:border-slate-400',
      ]"
      :style="
        store.workspaceId === ws.id
          ? { backgroundColor: ws.color }
          : {}
      "
    >
      <span
        v-if="ws.icon"
        :class="[
          'w-5 h-5 rounded inline-flex items-center justify-center text-[10px] font-bold',
          store.workspaceId === ws.id ? 'bg-white/20' : '',
        ]"
        :style="
          store.workspaceId === ws.id ? {} : { backgroundColor: ws.color, color: 'white' }
        "
      >
        {{ ws.icon }}
      </span>
      <span>{{ ws.display_name }}</span>
      <span
        v-if="ws.doc_count"
        :class="[
          'text-[10px] font-mono px-1 rounded',
          store.workspaceId === ws.id ? 'bg-white/20' : 'bg-slate-100',
        ]"
      >
        {{ ws.doc_count }}
      </span>
    </button>
  </div>
</template>
