<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import * as api from '../../api/client'

const workspaces = ref([])
const loading = ref(true)
const error = ref(null)

onMounted(async () => {
  try {
    workspaces.value = await api.listWorkspaces()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="max-w-6xl mx-auto p-6">
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-slate-800">Workspaces</h1>
      <p class="text-sm text-slate-500 mt-1">
        每個 workspace 是一個獨立部門：自己的 KB、agent workflow、聊天室。
      </p>
    </div>

    <div v-if="loading" class="text-slate-400 text-sm">載入中…</div>
    <div v-else-if="error" class="text-rose-600 text-sm">{{ error }}</div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <RouterLink
        v-for="ws in workspaces"
        :key="ws.id"
        :to="`/admin/workspaces/${ws.id}`"
        class="bg-white border border-slate-200 rounded-xl p-5 hover:shadow-md hover:border-slate-300 transition block"
      >
        <div class="flex items-center gap-3 mb-3">
          <div
            class="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold"
            :style="{ backgroundColor: ws.color }"
          >
            {{ ws.icon || ws.id.slice(0, 2).toUpperCase() }}
          </div>
          <div>
            <div class="font-semibold text-slate-800">{{ ws.display_name }}</div>
            <div class="text-xs text-slate-500 font-mono">{{ ws.id }}</div>
          </div>
        </div>
        <div class="text-sm text-slate-600 mb-3 line-clamp-2 min-h-[2.5rem]">{{ ws.description }}</div>
        <div class="flex items-center gap-4 text-xs text-slate-500">
          <span><span class="font-semibold text-slate-700">{{ ws.kb_count }}</span> KB</span>
          <span><span class="font-semibold text-slate-700">{{ ws.doc_count }}</span> documents</span>
          <span class="ml-auto">default kb: <span class="font-mono">{{ ws.default_kb }}</span></span>
        </div>
      </RouterLink>
    </div>

    <div class="mt-6 flex gap-3">
      <RouterLink
        to="/admin/traces"
        class="text-sm text-brand-600 hover:underline"
      >→ Trace Explorer</RouterLink>
    </div>
  </div>
</template>
