<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ChatWindow from '../components/ChatWindow.vue'
import AiTracePanel from '../components/AiTracePanel.vue'
import { useChatStore } from '../stores/chat'

const store = useChatStore()
const traceOpen = ref(false)

onMounted(async () => {
  await store.start()
})

onBeforeUnmount(() => {
  store.socket?.close()
})
</script>

<template>
  <div class="h-full flex relative overflow-hidden">
    <div class="flex-1 min-w-0">
      <ChatWindow @toggle-trace="traceOpen = !traceOpen" />
    </div>

    <div
      v-if="traceOpen"
      @click="traceOpen = false"
      class="lg:hidden absolute inset-0 bg-black/40 z-30"
    ></div>

    <div
      :class="[
        'absolute lg:static inset-y-0 right-0 z-40 w-full sm:w-96 transition-transform duration-200 ease-out',
        traceOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0',
      ]"
    >
      <AiTracePanel @close="traceOpen = false" />
    </div>
  </div>
</template>
