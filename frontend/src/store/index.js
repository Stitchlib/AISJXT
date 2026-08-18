import { reactive } from 'vue'

// 轻量级全局状态：跨页面共享检测结果、系统健康、连接状态、用户与告警。
// 通过 provide/inject 注入，组件使用 inject('store') 或 useStore() 访问。
const state = reactive({
  connected: false,
  systemHealth: null,
  cameras: [],
  user: null,
  alertUnread: 0,
  inspection: {
    running: false,
    detector_mode: 'simulation',
    total_processed: 0,
    last_result: null,
  },
})

export function setupStore(app) {
  const token = localStorage.getItem('aiqc_token')
  app.provide('store', state)
  return { token }
}

export function useStore() {
  return state
}

export const actions = {
  setConnected(v) {
    state.connected = v
  },
  setHealth(h) {
    state.systemHealth = h
  },
  setCameras(c) {
    state.cameras = c
  },
  setInspection(patch) {
    Object.assign(state.inspection, patch)
  },
  setUser(u) {
    state.user = u
  },
  setAlertUnread(n) {
    state.alertUnread = typeof n === 'number' ? n : 0
  },
  incAlertUnread(n = 1) {
    state.alertUnread += n
  },
}
