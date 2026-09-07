import client from './client'

// M7：视频流鉴权升级为一次性短时效 stream ticket，避免 JWT 暴露在 URL / 访问日志。
// 前端先向 /cameras/stream-ticket 换取 ticket，再把 ?ticket= 拼到流地址。
async function fetchStreamTicket() {
  const r = await client.get('/cameras/stream-ticket')
  return r.data.ticket
}

export const healthApi = {
  get: () => client.get('/health').then((r) => r.data),
  system: () => client.get('/system-health').then((r) => r.data),
}

export const cameraApi = {
  list: () => client.get('/cameras').then((r) => r.data),
  get: (id) => client.get(`/cameras/${id}`).then((r) => r.data),
  create: (payload) => client.post('/cameras', payload).then((r) => r.data),
  update: (id, payload) => client.put(`/cameras/${id}`, payload).then((r) => r.data),
  remove: (id) => client.delete(`/cameras/${id}`).then((r) => r.data),
  scan: (subnet) => client.get('/cameras/network/scan', { params: { subnet } }).then((r) => r.data),
  discover: (payload) => client.post('/cameras/discover', payload).then((r) => r.data),
  test: (payload) => client.post('/cameras/test', payload).then((r) => r.data),
  setActive: (id) => client.put(`/cameras/${id}/active`).then((r) => r.data),
  // M7：换取一次性短时效 stream ticket（见 fetchStreamTicket）
  streamTicket: fetchStreamTicket,
  videoUrl: async (id, fps = 15, annotate = true) => {
    const ticket = await fetchStreamTicket()
    return `/api/v1/cameras/${encodeURIComponent(id)}/video?ticket=${encodeURIComponent(ticket)}&fps=${fps}&annotate=${annotate}`
  },
  snapshotUrl: async (id, annotate = true, quality = 85) => {
    const ticket = await fetchStreamTicket()
    return `/api/v1/cameras/${encodeURIComponent(id)}/snapshot?ticket=${encodeURIComponent(ticket)}&annotate=${annotate}&quality=${quality}`
  },
  streamStatus: () => client.get('/cameras/streams/status').then((r) => r.data),
  // 免落库的临时预览：添加/配置摄像头前，用来源(与凭据)验证是否可取流
  previewUrl: async (source, username = '', password = '', fps = 12, annotate = false) => {
    const ticket = await fetchStreamTicket()
    const p = new URLSearchParams()
    p.set('ticket', ticket)
    p.set('source', source || '')
    p.set('username', username || '')
    p.set('password', password || '')
    p.set('fps', String(fps))
    p.set('annotate', String(annotate))
    return `/api/v1/cameras/preview/stream?${p.toString()}`
  },
  // 按来源字符串推断类型：前端本地显示用；后端也会再做一次归一化
  inferType: (source) => {
    if (!source) return 'simulation'
    const s = String(source).trim().toLowerCase()
    if (s.startsWith('rtsp://') || s.startsWith('rtsps://')) return 'rtsp'
    if (s.startsWith('http://') || s.startsWith('https://')) return 'http'
    if (/^\d+$/.test(s)) return 'usb'
    return 'simulation'
  },
}

export const configApi = {
  get: () => client.get('/config').then((r) => r.data),
  update: (payload) => client.put('/config', payload).then((r) => r.data),
}

export const detectionApi = {
  list: (params) => client.get('/detection-results', { params }).then((r) => r.data),
  get: (id) => client.get(`/detection-results/${id}`).then((r) => r.data),
  statistics: () => client.get('/detection-results/statistics').then((r) => r.data),
  exportCsv: () =>
    client.get('/detection-results/export', { params: { format: 'csv' }, responseType: 'blob' }).then((r) => r.data),
}

// G1 缺陷现场图访问：blobUrl 走 Bearer + objectURL（缩略图/弹窗内嵌 <img> 最稳妥，
// 避开一次性 ticket 只能消费一次的限制）；ticketUrl 供必须直连 <img src> 的场合。
export const mediaApi = {
  blobUrl: async (path) => {
    const enc = String(path).split('/').map(encodeURIComponent).join('/')
    const r = await client.get(`/media/${enc}`, { responseType: 'blob' })
    return URL.createObjectURL(r.data)
  },
  ticketUrl: async (path) => {
    const ticket = await fetchStreamTicket()
    const enc = String(path).split('/').map(encodeURIComponent).join('/')
    return `/api/v1/media/${enc}?ticket=${encodeURIComponent(ticket)}`
  },
  rootInfo: () => client.get('/media/root-info').then((r) => r.data),
}

export const authApi = {
  login: (username, password) => client.post('/auth/login', { username, password }).then((r) => r.data),
  me: () => client.get('/auth/me').then((r) => r.data),
}

export const alertsApi = {
  rules: () => client.get('/alerts/rules').then((r) => r.data),
  createRule: (payload) => client.post('/alerts/rules', payload).then((r) => r.data),
  updateRule: (id, payload) => client.put(`/alerts/rules/${id}`, payload).then((r) => r.data),
  removeRule: (id) => client.delete(`/alerts/rules/${id}`).then((r) => r.data),
  events: (params) => client.get('/alerts/events', { params }).then((r) => r.data),
  acknowledge: (id) => client.post(`/alerts/events/${id}/acknowledge`).then((r) => r.data),
  // G2 人工判定：verdict ∈ confirmed / false_positive / missed
  setVerdict: (id, payload) => client.put(`/alerts/events/${id}/verdict`, payload).then((r) => r.data),
  statistics: (params) => client.get('/alerts/statistics', { params }).then((r) => r.data),
  // G3 多渠道通知：测试发送（按规则配置的 webhook 渠道）
  testWebhook: (id) => client.post(`/alerts/rules/${id}/test`).then((r) => r.data),
}

export const reportsApi = {
  summary: (params) => client.get('/reports/summary', { params }).then((r) => r.data),
  // 带鉴权的 Blob 下载（window.open 无法附带 Bearer，故走 axios）
  exportExcel: () =>
    client.get('/reports/export', { params: { format: 'excel' }, responseType: 'blob' }).then((r) => r.data),
  exportCsv: () =>
    client.get('/reports/export', { params: { format: 'csv' }, responseType: 'blob' }).then((r) => r.data),
}

export const modelApi = {
  versions: () => client.get('/model-versions').then((r) => r.data),
  upload: (formData) =>
    client
      .post('/model-versions/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((r) => r.data),
  activate: (id) => client.post(`/model-versions/${id}/activate`).then((r) => r.data),
  remove: (id) => client.delete(`/model-versions/${id}`).then((r) => r.data),
  // 第二期 1.3 训练样本导出：已判定（confirmed/false_positive）缺陷帧 + 标注 → YOLO 目录 zip
  exportSamples: (params = {}) =>
    client.get('/model-versions/export-samples', { params, responseType: 'blob' }).then((r) => r.data),
}

export const usersApi = {
  list: () => client.get('/users').then((r) => r.data),
  create: (payload) => client.post('/users', payload).then((r) => r.data),
  update: (id, payload) => client.put(`/users/${id}`, payload).then((r) => r.data),
  remove: (id) => client.delete(`/users/${id}`).then((r) => r.data),
  // M6：改密码（admin 改他人 / 本人改自己需验旧密码）
  changePassword: (id, payload) => client.put(`/users/${id}/password`, payload).then((r) => r.data),
}

// L3 审计日志（admin 专属）
export const auditApi = {
  list: (params = {}) => client.get('/audit', { params }).then((r) => r.data),
}

export const inspectionApi = {
  // 支持 camera_id 与 batch_id（批次绑定，第二期 G4）；未传则走后端默认
  start: (params = {}) => client.post('/inspection/start', null, { params }).then((r) => r.data),
  stop: () => client.post('/inspection/stop').then((r) => r.data),
  status: () => client.get('/inspection/status').then((r) => r.data),
}

// G4 批次/工单管理
export const batchApi = {
  list: () => client.get('/batches').then((r) => r.data),
  get: (id) => client.get(`/batches/${id}`).then((r) => r.data),
  create: (payload) => client.post('/batches', payload).then((r) => r.data),
  end: (id) => client.post(`/batches/${id}/end`).then((r) => r.data),
  report: (id) => client.get(`/reports/batch/${id}`).then((r) => r.data),
}

// G7a SQLite 备份与恢复（仅 admin）
export const systemApi = {
  backup: () => client.post('/system/backup').then((r) => r.data),
  listBackups: () => client.get('/system/backups').then((r) => r.data),
}
