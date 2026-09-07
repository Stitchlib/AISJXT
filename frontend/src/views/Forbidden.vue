<template>
  <div class="forbidden">
    <el-result icon="warning" title="403 无访问权限" sub-title="当前账号无权访问该页面，请联系管理员或使用具备相应权限的账号登录。">
      <template #extra>
        <el-button type="primary" @click="goBack">返回仪表盘</el-button>
        <el-button @click="logout">退出登录</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { actions } from '@/store'
import { clearToken, clearUser } from '@/api/client'

const router = useRouter()

function goBack() {
  router.push('/dashboard')
}
function logout() {
  clearToken()
  clearUser()
  actions.setUser(null)
  router.push('/login')
}
</script>

<style scoped>
.forbidden {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
</style>
