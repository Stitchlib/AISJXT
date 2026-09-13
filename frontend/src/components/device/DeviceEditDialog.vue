<template>
  <el-dialog
    :model-value="modelValue"
    :title="'编辑设备 — ' + (camera?.id || '')"
    width="460px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert type="info" :closable="false" style="margin-bottom: 12px"
      title="来源与账号/密码仅管理员可修改；账号、密码留空表示保持不变。" />
    <el-form :model="form" label-width="90px">
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.type" style="width: 100%" :disabled="!canAdmin">
          <el-option label="RTSP" value="rtsp" />
          <el-option label="USB" value="usb" />
          <el-option label="HTTP" value="http" />
          <el-option label="仿真" value="simulation" />
        </el-select>
      </el-form-item>
      <el-form-item label="来源">
        <el-input v-model="form.source" :disabled="!canAdmin" placeholder="rtsp://... 或 0" />
      </el-form-item>
      <el-form-item label="账号">
        <el-input v-model="form.username" :disabled="!canAdmin" placeholder="留空=不修改" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" type="password" :disabled="!canAdmin" placeholder="留空=不修改" show-password />
      </el-form-item>
      <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  canAdmin: { type: Boolean, default: false },
  camera: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'save'])

// 来源默认显示掩码值；账号/密码留空=不修改；
// 含 ":***@" 的掩码回传由后端视为"未修改"，绝不写穿真实凭据
const form = reactive({ id: '', name: '', type: 'rtsp', source: '', username: '', password: '', enabled: true })
const original = reactive({ source: '' })

watch(
  () => props.camera,
  (row) => {
    if (!row) return
    form.id = row.id
    form.name = row.name
    form.type = row.type
    form.source = row.source_masked || row.source || ''
    form.username = ''
    form.password = ''
    form.enabled = row.enabled !== false
    original.source = row.source_masked || row.source || ''
  }
)

function onSave() {
  if (!form.name) {
    emit('invalid', '请填写名称')
    return
  }
  const payload = { name: form.name, enabled: form.enabled }
  if (form.type) payload.type = form.type
  // 仅当来源被真正改动（且不含掩码标记）才提交 → 后端按 admin 权限校验
  const src = (form.source || '').trim()
  if (src && src !== original.source && !src.includes(':***@')) payload.source = src
  if (form.username.trim()) payload.username = form.username.trim()
  if (form.password) payload.password = form.password
  emit('save', { id: form.id, payload })
}
</script>
