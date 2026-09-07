import { describe, it, expect } from 'vitest'
import { getBackoffDelay } from '@/utils/websocket'

// 验证 WS 重连指数退避：1s → 2s → 4s → … → 30s 封顶
describe('getBackoffDelay 指数退避', () => {
  it('第 1 次重试用 1s', () => {
    expect(getBackoffDelay(1)).toBe(1000)
  })
  it('第 2 次重试用 2s', () => {
    expect(getBackoffDelay(2)).toBe(2000)
  })
  it('第 3 次重试用 4s', () => {
    expect(getBackoffDelay(3)).toBe(4000)
  })
  it('增长符合 2 的幂次', () => {
    expect(getBackoffDelay(5)).toBe(16000)
  })
  it('封顶 30s', () => {
    expect(getBackoffDelay(10)).toBe(30000)
    expect(getBackoffDelay(100)).toBe(30000)
  })
})
