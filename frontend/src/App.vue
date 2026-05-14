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
    <header class="bg-white border-b border-slate-200">
      <div class="px-3 sm:px-6 py-2 sm:py-3 flex items-center gap-3 sm:gap-6">
        <RouterLink to="/" class="flex items-center gap-2 sm:gap-3 shrink-0 min-w-0">
          <div class="w-8 h-8 rounded-lg bg-brand-500 flex items-center justify-center text-white font-bold shrink-0">A</div>
          <div class="min-w-0">
            <div class="font-semibold text-slate-800 leading-tight">AISP</div>
            <div class="text-xs text-slate-500 truncate max-w-[120px] sm:max-w-[280px]">{{ subtitle }}</div>
          </div>
        </RouterLink>

        <WorkspaceSelector v-if="isChat" class="hidden md:flex flex-1 overflow-x-auto" />
        <div v-else class="flex-1"></div>
        <div v-if="isChat" class="md:hidden flex-1"></div>

        <nav class="flex items-center gap-1 shrink-0">
          <RouterLink
            to="/"
            class="px-2.5 sm:px-3 py-1.5 rounded-lg text-sm font-medium transition"
            :class="$route.name === 'chat' ? 'bg-brand-500 text-white' : 'text-slate-600 hover:bg-slate-100'"
          >
            Chat
          </RouterLink>
          <RouterLink
            to="/admin"
            class="px-2.5 sm:px-3 py-1.5 rounded-lg text-sm font-medium transition"
            :class="$route.path.startsWith('/admin') ? 'bg-slate-800 text-white' : 'text-slate-600 hover:bg-slate-100'"
          >
            Admin
          </RouterLink>
        </nav>
      </div>

      <WorkspaceSelector
        v-if="isChat"
        class="md:hidden border-t border-slate-100 px-3 py-2 overflow-x-auto"
      />
    </header>

    <main class="flex-1 min-h-0 overflow-y-auto">
      <RouterView />
    </main>
  </div>
</template>
