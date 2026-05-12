/**
 * 簡單的 WebSocket 包裝，支援自動重連與事件 callback。
 */
export class ChatSocket {
  constructor(roomId, { onEvent, onStatus } = {}) {
    this.roomId = roomId
    this.onEvent = onEvent || (() => {})
    this.onStatus = onStatus || (() => {})
    this.ws = null
    this.shouldReconnect = true
    this.reconnectDelay = 1000
  }

  get url() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    // Vite dev server proxies /ws to backend
    return `${proto}://${location.host}/ws/rooms/${this.roomId}`
  }

  connect() {
    this.onStatus('connecting')
    const ws = new WebSocket(this.url)
    this.ws = ws

    ws.onopen = () => {
      this.reconnectDelay = 1000
      this.onStatus('open')
    }
    ws.onclose = (ev) => {
      this.onStatus('closed')
      this.ws = null
      if (this.shouldReconnect && ev.code !== 4004) {
        setTimeout(() => this.connect(), this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 10000)
      }
    }
    ws.onerror = () => this.onStatus('error')
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data)
        this.onEvent(data)
      } catch (e) {
        console.error('Bad WS message', e, msg.data)
      }
    }
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  close() {
    this.shouldReconnect = false
    if (this.ws) this.ws.close()
  }
}
