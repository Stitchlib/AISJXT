import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import client, { setToken, clearToken, getToken } from '@/api/client'

// 用自定义 adapter 模拟后端，验证 401 自动刷新 + 原请求重放
function makeErr(status, config, data = {}) {
  const err = new Error('request failed')
  err.response = { status, data, config }
  err.config = config
  return err
}

describe('client 401 自动刷新拦截器', () => {
  let originalAdapter

  beforeEach(() => {
    originalAdapter = client.defaults.adapter
    setToken('OLD')
    client.defaults.adapter = async (config) => {
      if (config.url === '/auth/refresh') {
        return { data: { access_token: 'NEW' }, status: 200, statusText: 'OK', headers: {}, config }
      }
      if (config.url === '/protected') {
        if (!config.__replayed) {
          config.__replayed = true
          return Promise.reject(makeErr(401, config))
        }
        return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
      }
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    }
  })

  afterEach(() => {
    clearToken()
    client.defaults.adapter = originalAdapter
  })

  it('收到 401 时用 /auth/refresh 换新 token 并重放原请求', async () => {
    const resp = await client.get('/protected')
    expect(resp.data).toEqual({ ok: true })
    // 刷新后 localStorage 中的 token 应更新
    expect(getToken()).toBe('NEW')
  })
})
