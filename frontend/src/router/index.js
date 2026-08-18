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
import { getToken } from '@/api/client'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录', public: true } },
  { path: '/dashboard', name: 'dashboard', component: SystemDashboard, meta: { title: '系统仪表盘' } },
  { path: '/realtime', name: 'realtime', component: RealTimeInspection, meta: { title: '实时质检' } },
  { path: '/devices', name: 'devices', component: DeviceManagement, meta: { title: '设备管理' } },
  { path: '/model-monitor', name: 'model-monitor', component: ModelMonitoring, meta: { title: '模型监控' } },
  { path: '/quality-report', name: 'quality-report', component: QualityReport, meta: { title: '质检报告' } },
  { path: '/history', name: 'history', component: HistoryRecords, meta: { title: '历史记录' } },
  { path: '/system-config', name: 'system-config', component: SystemConfig, meta: { title: '系统配置' } },
  { path: '/alerts', name: 'alerts', component: Alerts, meta: { title: '告警中心' } },
  { path: '/users', name: 'users', component: UserManagement, meta: { title: '用户管理' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 全局前置守卫：访问受保护路由时若无 token 则跳登录；已登录访问登录页则跳仪表盘
router.beforeEach((to, from, next) => {
  const token = getToken()
  if (!to.meta.public && !token) {
    next({ path: '/login' })
  } else if (to.path === '/login' && token) {
    next({ path: '/dashboard' })
  } else {
    next()
  }
})

export default router
