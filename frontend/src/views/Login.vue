<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <div class="brand">AI 视觉质检系统</div>
      <div class="subtitle">请登录以继续使用</div>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="0" @submit.prevent>
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" size="large" :prefix-icon="UserIcon" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
            :prefix-icon="LockIcon"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onSubmit">
            登录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { authApi } from '@/api'
import { setToken } from '@/api/client'
import { actions } from '@/store'

const router = useRouter()
const formRef = ref(null)
const loading = ref(false)
const UserIcon = User
const LockIcon = Lock

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const data = await authApi.login(form.username, form.password)
      setToken(data.access_token)
      actions.setUser(data.user)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    } catch (e) {
      const detail = e.response?.data?.detail
      ElMessage.error(typeof detail === 'string' ? detail : '登录失败，请检查用户名或密码')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-wrap {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #409eff 100%);
}
.login-card { width: 360px; padding: 12px 24px 24px; }
.brand { font-size: 22px; font-weight: 700; text-align: center; color: #303133; margin-top: 8px; }
.subtitle { text-align: center; color: #909399; font-size: 13px; margin: 8px 0 20px; }
</style>
