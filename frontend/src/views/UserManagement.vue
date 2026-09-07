<template>
  <div>
    <h2>用户管理</h2>
    <el-alert
      v-if="!isAdmin"
      type="warning"
      :closable="false"
      title="当前账号非管理员，无用户管理权限（后端已强制校验）。"
      style="margin-bottom: 16px"
    />

    <el-tabs v-model="activeTab">
      <!-- 用户列表 -->
      <el-tab-pane label="用户列表" name="users">
        <el-card v-loading="loading" shadow="hover">
          <template #header>
            <div class="card-head">
              <b>系统用户</b>
              <el-button v-if="isAdmin" type="primary" size="small" @click="openDialog()">+ 新建用户</el-button>
            </div>
          </template>
          <el-empty v-if="!loading && users.length === 0" description="暂无用户" />
          <el-table v-else :data="users" border size="small">
            <el-table-column prop="username" label="用户名" min-width="140" />
            <el-table-column prop="display_name" label="显示名" min-width="140" />
            <el-table-column label="角色" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="roleTag(row.role)" size="small">{{ roleText(row.role) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="!row.disabled" type="success" size="small">启用</el-tag>
                <el-tag v-else type="info" size="small">禁用</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="200" show-overflow-tooltip />
            <el-table-column v-if="isAdmin" label="操作" width="250" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openDialog(row)">编辑</el-button>
                <el-button size="small" type="warning" @click="openPwd(row)">改密</el-button>
                <el-button type="danger" size="small" @click="remove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 审计日志（L3） -->
      <el-tab-pane v-if="isAdmin" label="审计日志" name="audit">
        <el-card v-loading="auditLoading" shadow="hover">
          <template #header>
            <div class="card-head">
              <b>管理操作审计流水</b>
              <el-button size="small" @click="loadAudit">刷新</el-button>
            </div>
          </template>
          <el-empty v-if="!auditLoading && auditItems.length === 0" description="暂无审计记录" />
          <el-table v-else :data="auditItems" border size="small">
            <el-table-column prop="timestamp" label="时间" min-width="200" show-overflow-tooltip />
            <el-table-column prop="actor" label="操作人" width="140" />
            <el-table-column prop="action" label="动作" width="180" show-overflow-tooltip />
            <el-table-column prop="target" label="对象" width="140" show-overflow-tooltip />
            <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
            <el-table-column prop="ip" label="来源 IP" width="140" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建/编辑用户 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑用户' : '新建用户'" width="440px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!editing" placeholder="登录账号，不可修改" />
        </el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" placeholder="可选" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="操作员" value="operator" />
            <el-option label="访客" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editing" label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="登录密码" />
        </el-form-item>
        <el-form-item v-else label="启用">
          <el-switch v-model="form.disabled" :active-value="false" :inactive-value="true" active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码（M6） -->
    <el-dialog v-model="pwdDialog" title="修改密码" width="420px">
      <el-form :model="pwdForm" label-width="96px">
        <el-alert
          v-if="pwdTarget && pwdTarget.username === store.user?.username"
          type="info"
          :closable="false"
          title="正在修改本人密码，需先验证当前密码。"
          style="margin-bottom: 12px"
        />
        <el-form-item v-if="pwdSelf" label="当前密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="当前登录密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePwd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi, auditApi } from '@/api'
import { useStore } from '@/store'

const store = useStore()
const isAdmin = computed(() => store.user?.role === 'admin')
const activeTab = ref('users')

const loading = ref(false)
const users = ref([])
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({
  username: '',
  display_name: '',
  role: 'operator',
  password: '',
  disabled: false,
})

// 审计日志（L3）
const auditLoading = ref(false)
const auditItems = ref([])

// 修改密码（M6）
const pwdDialog = ref(false)
const pwdSaving = ref(false)
const pwdTarget = ref(null)
const pwdSelf = computed(() => pwdTarget.value && pwdTarget.value.username === store.user?.username)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

function roleText(r) {
  return { admin: '管理员', operator: '操作员', viewer: '访客' }[r] || r
}
function roleTag(r) {
  return { admin: 'danger', operator: 'warning', viewer: 'info' }[r] || 'info'
}

async function load() {
  loading.value = true
  try {
    users.value = await usersApi.list()
  } catch (e) {
    ElMessage.error('加载用户失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function loadAudit() {
  auditLoading.value = true
  try {
    const res = await auditApi.list({ page: 1, page_size: 100 })
    auditItems.value = res.items || []
  } catch (e) {
    ElMessage.error('加载审计日志失败：' + (e.response?.data?.detail || e.message))
  } finally {
    auditLoading.value = false
  }
}

function openDialog(u) {
  editing.value = u || null
  if (u) {
    form.username = u.username
    form.display_name = u.display_name || ''
    form.role = u.role
    form.password = ''
    form.disabled = !!u.disabled
  } else {
    form.username = ''
    form.display_name = ''
    form.role = 'operator'
    form.password = ''
    form.disabled = false
  }
  dialog.value = true
}

async function save() {
  if (!editing.value && !form.username) {
    ElMessage.warning('请填写用户名')
    return
  }
  if (!editing.value && !form.password) {
    ElMessage.warning('请填写密码')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const patch = { display_name: form.display_name, role: form.role, disabled: form.disabled }
      await usersApi.update(editing.value.id, patch)
      ElMessage.success('已更新用户')
    } else {
      await usersApi.create({
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        role: form.role,
      })
      ElMessage.success('已新建用户')
    }
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function remove(u) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${u.username}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await usersApi.remove(u.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

function openPwd(u) {
  pwdTarget.value = u
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
  pwdDialog.value = true
}

async function savePwd() {
  if (!pwdForm.new_password || pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  if (pwdSelf.value && !pwdForm.old_password) {
    ElMessage.warning('请先填写当前密码')
    return
  }
  pwdSaving.value = true
  try {
    const payload = { new_password: pwdForm.new_password }
    if (pwdSelf.value) payload.old_password = pwdForm.old_password
    await usersApi.changePassword(pwdTarget.value.id, payload)
    ElMessage.success('密码已更新')
    pwdDialog.value = false
  } catch (e) {
    ElMessage.error('修改失败：' + (e.response?.data?.detail || e.message))
  } finally {
    pwdSaving.value = false
  }
}

onMounted(() => {
  load()
  if (isAdmin.value) loadAudit()
})
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
