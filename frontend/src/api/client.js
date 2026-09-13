import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'aiqc_token'
const USER_KEY = 'aiqc_user'
const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const client = axios.create({
  baseURL,
  timeout: 15000,
})

// 请求拦截：自动附带 JWT
client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ---- token 刷新（收到 401 时自动尝试一次换发并重放）----
let isRefreshing = false
let pendingQueue = []

function subscribeTokenRefresh(cb) {
  pendingQueue.push(cb)
}
function onRefreshed(token) {
  pendingQueue.forEach((cb) => cb(token))
  pendingQueue = []
}

async function doRefresh() {
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) throw new Error('no token')
  // 刷新接口 body 为 { token: "<当前jwt>" }，返回 { access_token }
  // 使用 _skipAuthRefresh 避免响应拦截器对刷新请求自身再次触发刷新逻辑
  const resp = await client.post('/auth/refresh', { token }, { _skipAuthRefresh: true })
  const newToken = resp.data && resp.data.access_token
  if (!newToken) throw new Error('no access_token')
  setToken(newToken)
  return newToken
}

// 统一的未授权处理：清凭证并跳登录页（避免重复跳转）
let redirecting = false
function handleUnauthorized() {
  clearToken()
  clearUser()
  if (!redirecting) {
    redirecting = true
    setTimeout(() => {
      if (window.location.hash !== '#/login') window.location.hash = '#/login'
      redirecting = false
    }, 0)
  }
}

// ---- 全局错误拦截：401 刷新 / 403 / 5xx 区分文案 ----
client.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const status = error.response && error.response.status
    const original = error.config || {}

    // 登录接口本身 401：交给调用方提示，不改写
    const isLogin = (original.url || '').includes('/auth/login')
    if (isLogin) return Promise.reject(error)

    // 401：尝试刷新一次后重放原请求
    if (status === 401 && !original._retry && !original._skipAuthRefresh) {
      if (!localStorage.getItem(TOKEN_KEY)) {
        // 已无 token（刷新接口自身 401 也会落到这里）
        ElMessage.error('登录已失效，请重新登录')
        handleUnauthorized()
        return Promise.reject(error)
      }
      if (isRefreshing) {
        // 并发请求排队，待刷新完成后用新 token 重放
        return new Promise((resolve) => {
          subscribeTokenRefresh((token) => {
            original.headers = original.headers || {}
            original.headers.Authorization = `Bearer ${token}`
            resolve(client(original))
          })
        })
      }
      original._retry = true
      isRefreshing = true
      try {
        const newToken = await doRefresh()
        onRefreshed(newToken)
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${newToken}`
        return client(original)
      } catch (e) {
        ElMessage.error('登录已失效，请重新登录')
        handleUnauthorized()
        return Promise.reject(e)
      } finally {
        isRefreshing = false
      }
    }

    // 越权 / 服务端错误：区分文案
    if (status === 403) {
      ElMessage.error('权限不足（403）：当前账号无权访问该资源')
    } else if (status >= 500) {
      ElMessage.error(`服务异常（${status}），请稍后重试`)
    } else if (status === 401) {
      // 刷新请求自身失败或已无 token 的兜底
      ElMessage.error('登录已失效，请重新登录')
      handleUnauthorized()
    }

    console.error('[API] 请求失败:', error.message)
    return Promise.reject(error)
  }
)

export const TOKEN_KEY_NAME = TOKEN_KEY
export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// 用户（含 role）持久化：路由守卫需同步读取角色，故落地到 localStorage
export function setUser(u) {
  if (u) localStorage.setItem(USER_KEY, JSON.stringify(u))
}
export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}
export function clearUser() {
  localStorage.removeItem(USER_KEY)
}

export default client
