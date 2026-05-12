<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import ChatWindow from '../components/ChatWindow.vue'
import AiTracePanel from '../components/AiTracePanel.vue'
import { useChatStore } from '../stores/chat'

const store = useChatStore()

onMounted(async () => {
  await store.start()
})

onBeforeUnmount(() => {
  store.socket?.close()
})
</script>

<template>
  <div class="h-full flex">
    <div class="flex-1 min-w-0">
      <ChatWindow />
    </div>
    <AiTracePanel />
  </div>
</template>
