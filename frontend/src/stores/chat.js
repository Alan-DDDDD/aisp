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
    // Phase 14 — 等回應期間的暫存進度，收到 ai_suggestion 後清空
    // { stage: 'thinking'|'understanding'|'retrieving'|'composing'|'synthesizing',
    //   label: '...', synthesisToolName: string|null }
    placeholder: null,
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
      this.placeholder = null
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
      } else if (ev.type === 'ai_thinking_start') {
        // 立刻插入 placeholder bubble — 收到 ai_suggestion 才會被換掉
        this.placeholder = {
          stage: 'thinking',
          label: '正在分析您的問題...',
          synthesisToolName: null,
        }
      } else if (ev.type === 'ai_stage_changed') {
        if (this.placeholder) {
          this.placeholder = {
            ...this.placeholder,
            stage: ev.stage,
            label: ev.label,
          }
        }
      } else if (ev.type === 'tool_synthesis_triggered') {
        if (this.placeholder) {
          // 合成是「重大事件」— 蓋掉 stage label，提醒 user 這條路徑會比較久
          this.placeholder = {
            ...this.placeholder,
            stage: 'synthesizing',
            label: `偵測到新需求，正在為您生成工具「${ev.tool_name}」...`,
            synthesisToolName: ev.tool_name,
          }
        }
      } else if (ev.type === 'ai_suggestion') {
        // 收到最終結果 — 清掉 placeholder，插入真實 AI 訊息
        const hadSynthesis = !!this.placeholder?.synthesisToolName
        this.placeholder = null
        this._upsertMessage({
          id: ev.message_id,
          room_id: ev.room_id,
          sender_role: 'ai',
          content: ev.draft,
          created_at: new Date().toISOString(),
          trace_id: ev.trace?.id,
          citations: ev.citations || [],
          extras: ev.extras || {},
          had_synthesis: hadSynthesis,
        })
        if (ev.trace) {
          this.tracesByMessageId[ev.message_id] = ev.trace
          this.selectedTraceMessageId = ev.message_id
        }
      } else if (ev.type === 'error') {
        // 出錯也要清 placeholder，否則 user 看到 placeholder 永遠停在那
        this.placeholder = null
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
