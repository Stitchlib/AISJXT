import { createRouter, createWebHashHistory } from 'vue-router'
import SystemDashboard from '@/views/SystemDashboard.vue'
import RealTimeInspection from '@/views/RealTimeInspection.vue'
import DeviceManagement from '@/views/DeviceManagement.vue'
import Login from '@/views/Login.vue'
import ModelMonitoring from '@/views/ModelMonitoring.vue'
import QualityReport from '@/views/QualityReport.vue'
import HistoryRecords from '@/views/HistoryRecords.vue'
import SystemConfig from '@/views/SystemConfig.vue'
import Alerts from '@/views/Alerts.vue'
import UserManagement from '@/views/UserManagement.vue'
import Forbidden from '@/views/Forbidden.vue'
import { getToken, getUser, setUser, clearToken, clearUser } from '@/api/client'
import { actions } from '@/store'
import { authApi } from '@/api'

// 路由元信息增加 roles：限制可访问角色。缺省（无 roles）对所有已登录角色开放。
// 角色约定（与后端一致）：admin（管理员）/ operator（操作员）/ viewer（访客，只读）
const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录', public: true } },
  { path: '/403', name: 'forbidden', component: Forbidden, meta: { title: '无访问权限' } },
  { path: '/dashboard', name: 'dashboard', component: SystemDashboard, meta: { title: '系统仪表盘' } },
  { path: '/realtime', name: 'realtime', component: RealTimeInspection, meta: { title: '实时质检' } },
  { path: '/devices', name: 'devices', component: DeviceManagement, meta: { title: '设备管理' } },
  { path: '/model-monitor', name: 'model-monitor', component: ModelMonitoring, meta: { title: '模型监控' } },
  { path: '/quality-report', name: 'quality-report', component: QualityReport, meta: { title: '质检报告' } },
  { path: '/history', name: 'history', component: HistoryRecords, meta: { title: '历史记录' } },
  // 系统配置：仅管理员（PUT /config 需要 admin，viewer 会得 403）
  { path: '/system-config', name: 'system-config', component: SystemConfig, meta: { title: '系统配置', roles: ['admin'] } },
  { path: '/alerts', name: 'alerts', component: Alerts, meta: { title: '告警中心' } },
  // 用户管理：仅管理员
  { path: '/users', name: 'users', component: UserManagement, meta: { title: '用户管理', roles: ['admin'] } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 用户角色解析：优先读 localStorage（登录时已落地），否则用 token 回源 /auth/me 一次
let userPromise = null
function ensureUser() {
  const cached = getUser()
  if (cached && cached.role) return Promise.resolve(cached)
  if (!getToken()) return Promise.resolve(null)
  if (!userPromise) {
    userPromise = authApi
      .me()
      .then((u) => {
        actions.setUser(u)
        setUser(u)
        return u
      })
      .catch(() => {
        clearToken()
        clearUser()
        return null
      })
  }
  return userPromise
}

// 全局前置守卫：未登录跳登录；受限路由校验角色；越权跳转 403
router.beforeEach(async (to) => {
  const token = getToken()

  // 公开页
  if (to.meta.public) {
    if (to.path === '/login' && token) return { path: '/dashboard' }
    return true
  }

  // 未登录 → 登录页
  if (!token) return { path: '/login' }

  // 受限路由：校验角色
  const roles = to.meta.roles
  if (Array.isArray(roles) && roles.length) {
    const user = await ensureUser()
    const role = user && user.role
    if (!role || !roles.includes(role)) {
      return { path: '/403' }
    }
  }
  return true
})

export default router
