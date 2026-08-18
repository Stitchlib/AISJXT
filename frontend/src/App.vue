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
        <el-menu-item index="/dashboard">📊 系统仪表盘</el-menu-item>
        <el-menu-item index="/realtime">🔍 实时质检</el-menu-item>
        <el-menu-item index="/devices">🎥 设备管理</el-menu-item>
        <el-menu-item index="/model-monitor">🧠 模型监控</el-menu-item>
        <el-menu-item index="/quality-report">📈 质检报告</el-menu-item>
        <el-menu-item index="/history">🗂️ 历史记录</el-menu-item>
        <el-menu-item index="/system-config">⚙️ 系统配置</el-menu-item>
        <el-menu-item index="/alerts">🔔 告警中心</el-menu-item>
        <el-menu-item index="/users">👤 用户管理</el-menu-item>
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
import { alertsApi } from '@/api'

const store = useStore()
const route = useRoute()
const router = useRouter()
const active = computed(() => route.path)
const isLogin = computed(() => route.name === 'login' || route.path === '/login')

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
      }
    },
    (status) => actions.setConnected(status)
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
