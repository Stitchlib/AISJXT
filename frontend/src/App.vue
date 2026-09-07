<template>
  <router-view v-if="isLogin" />

  <el-container v-else class="app">
    <el-aside width="220px" class="aside">
      <div class="logo">映己 AI 视觉质检</div>
      <el-menu
        :default-active="active"
        router
        class="menu"
        background-color="#1f2d3d"
        text-color="#c0c4cc"
        active-text-color="#ffffff"
      >
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          {{ m.icon }} {{ m.label }}
        </el-menu-item>
      </el-menu>
      <div class="conn" :class="store.connected ? 'ok' : 'bad'">
        后端连接：{{ store.connected ? '已连接' : '未连接' }}
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="title">{{ route.meta.title || '映己 AI 视觉质检' }}</div>
        <div class="user">
          <el-badge :value="store.alertUnread" :hidden="!store.alertUnread" :max="99" class="badge">
            <el-button text @click="goAlerts">🔔 告警</el-button>
          </el-badge>
          <span class="uname">{{ store.user?.display_name || store.user?.username || '未登录' }}</span>
          <el-tag size="small" :type="roleTagType">{{ roleText }}</el-tag>
          <el-button type="primary" text @click="logout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createWebSocket } from '@/utils/websocket'
import { actions, useStore } from '@/store'
import { clearToken, getToken } from '@/api/client'
import { alertsApi, inspectionApi } from '@/api'

const store = useStore()
const route = useRoute()
const router = useRouter()
const active = computed(() => route.path)
const isLogin = computed(() => route.name === 'login' || route.path === '/login')

// 侧边栏菜单：含 roles 的入口仅对指定角色可见（admin 专属：系统配置、用户管理）
const allMenus = [
  { path: '/dashboard', label: '系统仪表盘', icon: '📊' },
  { path: '/realtime', label: '实时质检', icon: '🔍' },
  { path: '/devices', label: '设备管理', icon: '🎥' },
  { path: '/model-monitor', label: '模型监控', icon: '🧠' },
  { path: '/quality-report', label: '质检报告', icon: '📈' },
  { path: '/history', label: '历史记录', icon: '🗂️' },
  { path: '/system-config', label: '系统配置', icon: '⚙️', roles: ['admin'] },
  { path: '/alerts', label: '告警中心', icon: '🔔' },
  { path: '/users', label: '用户管理', icon: '👤', roles: ['admin'] },
]
const menus = computed(() => {
  const role = store.user?.role
  return allMenus.filter((m) => !m.roles || (role && m.roles.includes(role)))
})

const roleText = computed(() => {
  const map = { admin: '管理员', operator: '操作员', viewer: '访客' }
  return map[store.user?.role] || store.user?.role || '未登录'
})
const roleTagType = computed(() => {
  const map = { admin: 'danger', operator: 'warning', viewer: 'info' }
  return map[store.user?.role] || 'info'
})

let ws = null

function goAlerts() {
  router.push('/alerts')
}

function logout() {
  clearToken()
  actions.setUser(null)
  actions.setAlertUnread(0)
  router.push('/login')
}

// 重连成功后对齐：拉取检测状态 + 未读告警数
async function realignState() {
  try {
    const st = await inspectionApi.status()
    actions.setInspection({
      running: !!st.running,
      detector_mode: st.detector_mode || store.inspection.detector_mode,
      total_processed: st.total_processed || store.inspection.total_processed,
    })
  } catch (_) {
    /* 对齐失败不影响连接 */
  }
  if (getToken()) {
    alertsApi
      .events({ acknowledged: false, page: 1, page_size: 1 })
      .then((r) => actions.setAlertUnread(r.total || 0))
      .catch(() => {})
  }
}

onMounted(() => {
  // 初始化未确认告警数（无 token 时跳过，否则登录页会触发 401）
  if (getToken()) {
    alertsApi
      .events({ acknowledged: false, page: 1, page_size: 1 })
      .then((r) => actions.setAlertUnread(r.total || 0))
      .catch(() => {})
  }

  ws = createWebSocket(
    (msg) => {
      if (msg.type === 'detection_result') {
        actions.setInspection({ last_result: msg.data, running: true })
        store.inspection.total_processed += 1
      } else if (msg.type === 'control') {
        if (msg.action === 'stop') actions.setInspection({ running: false })
        if (msg.action === 'start') actions.setInspection({ running: true })
      } else if (msg.type === 'alert') {
        const ids = (msg.data && msg.data.ids) || []
        actions.incAlertUnread(ids.length || 1)
        ElMessage.warning(`收到告警${msg.data?.camera_id ? '（摄像头 ' + msg.data.camera_id + '）' : ''}`)
      } else if (msg.type === 'error') {
        // 鉴权/越权错误帧（如 viewer 发送 start/stop 收到 4403）
        if (msg.code === 4403) {
          ElMessage.warning('权限不足：' + (msg.message || '当前角色无权执行该操作'))
        } else {
          ElMessage.error(msg.message || 'WebSocket 错误')
        }
      }
    },
    (status) => actions.setConnected(status),
    { onReconnect: realignState }
  )
})

onUnmounted(() => ws && ws.close())
</script>

<style scoped>
.app { height: 100vh; }
.aside { background: #1f2d3d; color: #fff; display: flex; flex-direction: column; }
.logo { font-size: 18px; font-weight: 700; padding: 18px 16px; color: #fff; }
.menu { background: transparent; border-right: none; flex: 1; }
.conn { padding: 12px 16px; font-size: 13px; }
.conn.ok { color: #67c23a; }
.conn.bad { color: #f56c6c; }
.header {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #ebeef5;
}
.header .title { font-size: 16px; font-weight: 600; color: #303133; }
.user { display: flex; align-items: center; gap: 12px; }
.uname { font-size: 14px; color: #606266; }
.badge { margin-right: 4px; }
.main { background: #f5f7fa; }
</style>
