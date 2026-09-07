// WebSocket 客户端：指数退避重连 + 页面可见性立即重试 + 重连后状态对齐。
// 默认使用同源地址，由 Vite dev proxy / nginx 将 /ws 转发到后端。
// 鉴权（第三期 1.3/M3）：连接前先 POST /ws-ticket 换一次性票据（30s），
// 以 ws://<host>/ws?ticket=<ticket> 握手——JWT 不再出现在 URL/access log。
// 换票失败（离线/过期）时退化为"裸连接 + 首帧 auth"兜底，JWT 同样不进 URL。
import client from '@/api/client'
import { getToken, clearToken, clearUser } from '@/api/client'

const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_BASE = import.meta.env.VITE_WS_URL || `${protocol}//${location.host}/ws`

// 纯函数：重连退避延迟（毫秒）。1s → 2s → 4s → … → 30s 封顶
export function getBackoffDelay(attempt) {
  const clamped = Math.max(0, attempt - 1) // 第 1 次重试用 1s
  return Math.min(30000, 1000 * 2 ** clamped)
}

// 换取一次性 WS 票据；失败返回 null（调用方走首帧 auth 兜底）
export async function acquireTicket() {
  try {
    const resp = await client.post('/ws-ticket', {}, { timeout: 5000 })
    return (resp.data && resp.data.ticket) || null
  } catch (_) {
    return null
  }
}

function buildWsUrl(ticket) {
  if (!ticket) return WS_BASE
  const sep = WS_BASE.includes('?') ? '&' : '?'
  return `${WS_BASE}${sep}ticket=${encodeURIComponent(ticket)}`
}

export function createWebSocket(onMessage, onStatus, options = {}) {
  const { onReconnect } = options
  let ws
  let reconnectTimer = null
  let closedByUser = false
  let attempt = 0

  function redirectLogin() {
    clearToken()
    clearUser()
    if (window.location.hash !== '#/login') window.location.hash = '#/login'
  }

  async function connect() {
    // 每次连接（含重连）都重新换票：票据是一次性的，30s 后也会过期
    const ticket = getToken() ? await acquireTicket() : null
    if (closedByUser) return // 等待换票期间组件可能已卸载
    ws = new WebSocket(buildWsUrl(ticket))
    ws.onopen = () => {
      attempt = 0 // 连接成功，重置退避计数
      onStatus && onStatus(true)
      // 兜底路径：未能换票时以首帧 auth 完成鉴权（JWT 不落 URL）
      if (!ticket && getToken()) {
        ws.send(JSON.stringify({ action: 'auth', token: getToken() }))
      }
      // 重连成功后主动对齐检测状态与未读告警
      if (typeof onReconnect === 'function') {
        try {
          onReconnect()
        } catch (_) {
          /* 忽略对齐过程中的错误 */
        }
      }
    }
    ws.onclose = (e) => {
      onStatus && onStatus(false)
      // 鉴权失败：后端直接关闭（code 4401），不再重连
      if (e && e.code === 4401) {
        redirectLogin()
        return
      }
      if (!closedByUser) scheduleReconnect()
    }
    ws.onerror = () => onStatus && onStatus(false)
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        // 错误帧（如 viewer 发送 start/stop 收到 {type:"error", code:4403}）
        if (msg && msg.type === 'error') {
          onMessage && onMessage(msg)
          return
        }
        onMessage && onMessage(msg)
      } catch (_) {
        /* 忽略非 JSON 消息 */
      }
    }
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer)
    attempt += 1
    const delay = getBackoffDelay(attempt)
    reconnectTimer = setTimeout(connect, delay)
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }

  function close() {
    closedByUser = true
    clearTimeout(reconnectTimer)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibility)
    }
    ws && ws.close()
  }

  // 页面重新可见时若处于断开状态，立即重试（重置退避）
  function onVisibility() {
    if (document.visibilityState === 'visible' && !closedByUser) {
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        clearTimeout(reconnectTimer)
        attempt = 0
        connect()
      }
    }
  }
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
  }

  connect()
  return { send, close }
}
