// WebSocket 客户端：自动重连 + 状态回调。供实时质检页与全局连接状态使用。
// 默认使用同源地址，让 Vite dev proxy / nginx 统一将 /ws 转发到后端，避免前端
// 直连 8000 端口（在 dev 场景或生产代理后 8000 通常不可达）。
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_URL = import.meta.env.VITE_WS_URL || `${protocol}//${location.host}/ws`

export function createWebSocket(onMessage, onStatus) {
  let ws
  let reconnectTimer = null
  let closedByUser = false

  function connect() {
    ws = new WebSocket(WS_URL)
    ws.onopen = () => onStatus && onStatus(true)
    ws.onclose = () => {
      onStatus && onStatus(false)
      if (!closedByUser) scheduleReconnect()
    }
    ws.onerror = () => onStatus && onStatus(false)
    ws.onmessage = (e) => {
      try {
        onMessage && onMessage(JSON.parse(e.data))
      } catch (_) {
        /* 忽略非 JSON 消息 */
      }
    }
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(connect, 3000)
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }

  function close() {
    closedByUser = true
    clearTimeout(reconnectTimer)
    ws && ws.close()
  }

  connect()
  return { send, close }
}
