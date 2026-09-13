<template>
  <el-dialog
    :model-value="modelValue"
    title="添加设备"
    width="460px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form :model="form" label-width="90px">
      <el-form-item label="设备ID"><el-input v-model="form.id" placeholder="如 cam_002" /></el-form-item>
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.type" style="width: 100%">
          <el-option label="RTSP" value="rtsp" />
          <el-option label="USB" value="usb" />
          <el-option label="HTTP" value="http" />
          <el-option label="仿真" value="simulation" />
        </el-select>
      </el-form-item>
      <el-form-item label="来源"><el-input v-model="form.source" placeholder="rtsp://... 或 0" /></el-form-item>
      <el-form-item label="账号"><el-input v-model="form.username" placeholder="匿名可留空" /></el-form-item>
      <el-form-item label="密码"><el-input v-model="form.password" type="password" placeholder="匿名可留空" show-password /></el-form-item>
      <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
    </el-form>
    <div v-if="previewSrc" class="add-preview">
      <div class="add-preview-head">
        <span>实时预览（保存前先确认可取流）</span>
        <el-button size="small" text type="primary" @click="reloadPreview">刷新预览</el-button>
      </div>
      <div class="add-preview-wrap">
        <img :key="previewKey" :src="previewSrc" class="add-preview-img" alt="摄像头预览" @error="onPreviewError" />
        <el-alert v-if="previewError" type="warning" :closable="false" :title="previewError" />
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button :loading="testing" @click="emit('test', { ...form })">测试连接</el-button>
      <el-button type="primary" :loading="saving" @click="emit('save', { ...form })">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, computed, watch } from 'vue'
import { cameraApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  testing: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'save', 'test'])

const form = reactive({ id: '', name: '', type: 'simulation', source: '', enabled: true, username: '', password: '' })

const previewReload = ref(0)
const previewError = ref('')
const previewSrc = ref('')
const previewKey = computed(() => `add-${previewReload.value}`)

async function loadPreview() {
  const src = form.source && form.source.trim()
  if (!src) {
    previewSrc.value = ''
    return
  }
  previewError.value = ''
  try {
    previewSrc.value = await cameraApi.previewUrl(src, form.username, form.password, 12)
  } catch (e) {
    previewSrc.value = ''
    previewError.value = '预览地址获取失败：' + (e.response?.data?.detail || e.message)
  }
}
function onPreviewError() {
  previewError.value = '该来源暂时取不到画面（地址/凭据/网络不可达，或设备未联网）'
}
function reloadPreview() {
  previewError.value = ''
  previewReload.value += 1
  loadPreview()
}

// 打开时重置表单；未手动切换类型时按来源自动推断：rtsp:// → rtsp，http:// → http，纯数字 → usb
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    form.id = ''
    form.name = ''
    form.type = 'simulation'
    form.source = ''
    form.enabled = true
    form.username = ''
    form.password = ''
    previewSrc.value = ''
    previewError.value = ''
  }
)
watch(
  () => form.source,
  (s) => {
    if (!props.modelValue) return
    if (form.type === 'simulation' || form.type === '') {
      form.type = cameraApi.inferType(s)
    }
    previewError.value = ''
    loadPreview()
  }
)

defineExpose({ form })
</script>

<style scoped>
.add-preview { margin: 4px 0 8px; border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; background: #fafafa; }
.add-preview-head { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: #606266; margin-bottom: 6px; }
.add-preview-wrap { width: 100%; min-height: 200px; background: #000; border-radius: 4px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.add-preview-img { width: 100%; display: block; }
</style>
