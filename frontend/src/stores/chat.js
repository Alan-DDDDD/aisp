import { defineStore } from 'pinia'
import * as api from '../api/client'
import { ChatSocket } from '../ws/client'

const STORAGE_KEY_WS = 'aisp.workspace'

export const useChatStore = defineStore('chat', {
  state: () => ({
    workspaces: [],
    workspaceId: localStorage.getItem(STORAGE_KEY_WS) || 'cs',
    roomId: null,
    messages: [],
    tracesByMessageId: {},
    connectionStatus: 'idle', // idle | connecting | open | closed | error
    selectedTraceMessageId: null,
    error: null,
    socket: null,
  }),
  getters: {
    selectedTrace(state) {
      return state.selectedTraceMessageId
        ? state.tracesByMessageId[state.selectedTraceMessageId] || null
        : null
    },
    currentWorkspace(state) {
      return state.workspaces.find((w) => w.id === state.workspaceId) || null
    },
  },
  actions: {
    async loadWorkspaces() {
      try {
        const list = await api.listWorkspaces()
        this.workspaces = list
        if (list.length && !list.find((w) => w.id === this.workspaceId)) {
          this.workspaceId = list[0].id
          localStorage.setItem(STORAGE_KEY_WS, this.workspaceId)
        }
      } catch (e) {
        this.error = `Failed to load workspaces: ${e.message}`
        throw e
      }
    },

    async start() {
      await this.loadWorkspaces()
      await this._openWorkspace(this.workspaceId)
    },

    async switchWorkspace(id) {
      if (!id || id === this.workspaceId) return
      localStorage.setItem(STORAGE_KEY_WS, id)
      this.workspaceId = id
      this._reset()
      await this._openWorkspace(id)
    },

    async _openWorkspace(workspaceId) {
      try {
        const room = await api.createRoom(workspaceId)
        this.roomId = room.id
      } catch (e) {
        this.error = `Failed to create room: ${e.message}`
        throw e
      }
      this._connect()
    },

    _reset() {
      if (this.socket) {
        this.socket.close()
        this.socket = null
      }
      this.roomId = null
      this.messages = []
      this.tracesByMessageId = {}
      this.selectedTraceMessageId = null
      this.connectionStatus = 'idle'
      this.error = null
    },

    _connect() {
      if (!this.roomId) throw new Error('roomId missing')
      if (this.socket) this.socket.close()
      this.socket = new ChatSocket(this.roomId, {
        onStatus: (s) => {
          this.connectionStatus = s
        },
        onEvent: (ev) => this._handleEvent(ev),
      })
      this.socket.connect()
    },

    sendUserMessage(content) {
      const trimmed = (content || '').trim()
      if (!trimmed) return false
      return this.socket?.send({ type: 'user_message', content: trimmed })
    },

    selectTrace(messageId) {
      this.selectedTraceMessageId = messageId
    },

    _handleEvent(ev) {
      if (ev.type === 'user_message') {
        this._upsertMessage(ev.message)
      } else if (ev.type === 'ai_suggestion') {
        this._upsertMessage({
          id: ev.message_id,
          room_id: ev.room_id,
          sender_role: 'ai',
          content: ev.draft,
          created_at: new Date().toISOString(),
          trace_id: ev.trace?.id,
          citations: ev.citations || [],
          extras: ev.extras || {},
        })
        if (ev.trace) {
          this.tracesByMessageId[ev.message_id] = ev.trace
          this.selectedTraceMessageId = ev.message_id
        }
      } else if (ev.type === 'error') {
        this.error = ev.message
      }
    },

    _upsertMessage(msg) {
      const idx = this.messages.findIndex((m) => m.id === msg.id)
      if (idx === -1) this.messages.push(msg)
      else this.messages[idx] = { ...this.messages[idx], ...msg }
    },
  },
})
