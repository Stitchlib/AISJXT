import axios from 'axios'

const TOKEN_KEY = 'aiqc_token'
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

// 响应拦截：统一可见性 + 401 清除 token 并跳登录
let redirecting = false
client.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response && error.response.status
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      const url = error.config && error.config.url ? error.config.url : ''
      // 登录接口本身的 401 不跳转，交由调用方提示
      if (!url.includes('/auth/login') && !redirecting) {
        redirecting = true
        setTimeout(() => {
          if (window.location.hash !== '#/login') {
            window.location.hash = '#/login'
          }
          redirecting = false
        }, 0)
      }
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

export default client
