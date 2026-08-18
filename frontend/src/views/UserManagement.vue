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
        <el-table-column v-if="isAdmin" label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDialog(row)">编辑</el-button>
            <el-button type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi } from '@/api'
import { useStore } from '@/store'

const store = useStore()
const isAdmin = computed(() => store.user?.role === 'admin')

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

onMounted(load)
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
