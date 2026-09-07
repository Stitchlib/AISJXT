import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import client from '@/api/client'
import { cameraApi } from '@/api/index'

// M7 视频流鉴权升级：前端先换一次性 stream-ticket，再把 ?ticket= 拼到流地址，
// 禁止把 JWT 以 ?token= 形式暴露在 URL / 访问日志中。这里验证 ticket 流与替换正确性。
function mockAdapter(handler) {
  return async (config) => handler(config)
}

const OK = (data) => ({ data, status: 200, statusText: 'OK', headers: {}, config: {} })

describe('M7 视频流 stream-ticket 鉴权', () => {
  let originalAdapter

  beforeEach(() => {
    originalAdapter = client.defaults.adapter
    client.defaults.adapter = mockAdapter((config) => {
      if (config.url === '/cameras/stream-ticket') {
        return Promise.resolve(OK({ ticket: 'SHORT_LIVED_TICKET_123' }))
      }
      return Promise.resolve(OK({}))
    })
  })

  afterEach(() => {
    client.defaults.adapter = originalAdapter
  })

  it('streamTicket() 返回后端签发的一次性 ticket', async () => {
    expect(await cameraApi.streamTicket()).toBe('SHORT_LIVED_TICKET_123')
  })

  it('videoUrl 使用 ?ticket= 且不暴露 JWT', async () => {
    const url = await cameraApi.videoUrl('cam1', 15, true)
    expect(url).toContain('ticket=SHORT_LIVED_TICKET_123')
    expect(url).not.toContain('token=')
    expect(url).toContain('/api/v1/cameras/cam1/video')
    expect(url).toContain('fps=15')
    expect(url).toContain('annotate=true')
  })

  it('snapshotUrl 携带 ticket 与质量参数', async () => {
    const url = await cameraApi.snapshotUrl('cam2', true, 90)
    expect(url).toContain('ticket=SHORT_LIVED_TICKET_123')
    expect(url).not.toContain('token=')
    expect(url).toContain('/api/v1/cameras/cam2/snapshot')
    expect(url).toContain('quality=90')
  })

  it('previewUrl 携带 ticket 与来源/凭据参数', async () => {
    const url = await cameraApi.previewUrl('rtsp://host/stream', 'u', 'p', 12, false)
    expect(url).toContain('ticket=SHORT_LIVED_TICKET_123')
    expect(url).not.toContain('token=')
    expect(url).toContain('source=rtsp%3A%2F%2Fhost%2Fstream')
    expect(url).toContain('username=u')
    expect(url).toContain('password=p')
  })

  it('ticket 获取失败时 videoUrl 应 rejected（视图侧捕获并提示）', async () => {
    client.defaults.adapter = mockAdapter((config) => {
      if (config.url === '/cameras/stream-ticket') {
        return Promise.reject(new Error('401 unauthorized'))
      }
      return Promise.resolve(OK({}))
    })
    await expect(cameraApi.videoUrl('cam1')).rejects.toThrow()
  })
})
