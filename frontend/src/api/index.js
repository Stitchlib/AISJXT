import client from './client'

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
  setActive: (id) => client.put(`/cameras/${id}/active`).then((r) => r.data),
}

export const configApi = {
  get: () => client.get('/config').then((r) => r.data),
  update: (payload) => client.put('/config', payload).then((r) => r.data),
}

export const detectionApi = {
  list: (params) => client.get('/detection-results', { params }).then((r) => r.data),
  statistics: () => client.get('/detection-results/statistics').then((r) => r.data),
  exportCsv: () =>
    client.get('/detection-results/export', { params: { format: 'csv' }, responseType: 'blob' }).then((r) => r.data),
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
}

export const usersApi = {
  list: () => client.get('/users').then((r) => r.data),
  create: (payload) => client.post('/users', payload).then((r) => r.data),
  update: (id, payload) => client.put(`/users/${id}`, payload).then((r) => r.data),
  remove: (id) => client.delete(`/users/${id}`).then((r) => r.data),
}

export const inspectionApi = {
  start: (camera_id) => client.post('/inspection/start', null, { params: { camera_id } }).then((r) => r.data),
  stop: () => client.post('/inspection/stop').then((r) => r.data),
  status: () => client.get('/inspection/status').then((r) => r.data),
}
