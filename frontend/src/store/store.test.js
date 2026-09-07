import { describe, it, expect } from 'vitest'
import { useStore, actions } from '@/store'

// 校验轻量 reactive store 的 actions 行为
describe('store actions', () => {
  it('未读告警计数 set/inc 正常', () => {
    actions.setAlertUnread(3)
    expect(useStore().alertUnread).toBe(3)
    actions.incAlertUnread(2)
    expect(useStore().alertUnread).toBe(5)
    actions.incAlertUnread() // 默认 +1
    expect(useStore().alertUnread).toBe(6)
  })

  it('setUser 写入用户与角色', () => {
    actions.setUser({ username: 'alice', role: 'admin' })
    expect(useStore().user.role).toBe('admin')
  })

  it('setInspection 合并检测状态', () => {
    actions.setInspection({ running: true, total_processed: 10 })
    expect(useStore().inspection.running).toBe(true)
    expect(useStore().inspection.total_processed).toBe(10)
  })
})
