<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, RouterView, RouterLink } from 'vue-router'
import WorkspaceSelector from './components/WorkspaceSelector.vue'
import { useChatStore } from './stores/chat'

const route = useRoute()
const store = useChatStore()

onMounted(async () => {
  if (!store.workspaces.length) {
    try {
      await store.loadWorkspaces()
    } catch {
      /* ignore — chat page handles its own load */
    }
  }
})

const isChat = computed(() => route.name === 'chat')
const subtitle = computed(() => {
  if (isChat.value) {
    const ws = store.currentWorkspace
    return ws ? ws.description : 'Multi-Department Agentic Workspace'
  }
  return 'Admin Console'
})
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6">
      <RouterLink to="/" class="flex items-center gap-3 shrink-0">
        <div class="w-8 h-8 rounded-lg bg-brand-500 flex items-center justify-center text-white font-bold">A</div>
        <div>
          <div class="font-semibold text-slate-800">AISP</div>
          <div class="text-xs text-slate-500 truncate max-w-[280px]">{{ subtitle }}</div>
        </div>
      </RouterLink>

      <WorkspaceSelector v-if="isChat" class="flex-1 overflow-x-auto" />
      <div v-else class="flex-1"></div>

      <nav class="flex items-center gap-1 shrink-0">
        <RouterLink
          to="/"
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition"
          :class="$route.name === 'chat' ? 'bg-brand-500 text-white' : 'text-slate-600 hover:bg-slate-100'"
        >
          Chat
        </RouterLink>
        <RouterLink
          to="/admin"
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition"
          :class="$route.path.startsWith('/admin') ? 'bg-slate-800 text-white' : 'text-slate-600 hover:bg-slate-100'"
        >
          Admin
        </RouterLink>
      </nav>
    </header>

    <main class="flex-1 min-h-0 overflow-y-auto">
      <RouterView />
    </main>
  </div>
</template>
