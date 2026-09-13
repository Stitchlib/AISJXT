<template>
  <el-dialog
    :model-value="modelValue"
    title="发现并自动添加网络摄像头"
    width="460px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
      title="将扫描网段、逐一探测常见 RTSP 地址，验证可取流后自动写入配置并设为当前摄像头。"
    />
    <el-form
      :model="form"
      label-width="92px"
    >
      <el-form-item label="网段">
        <el-input
          v-model="form.subnet"
          placeholder="如 192.168.1"
        />
      </el-form-item>
      <el-form-item label="账号">
        <el-input
          v-model="form.username"
          placeholder="匿名可留空"
        />
      </el-form-item>
      <el-form-item label="密码">
        <el-input
          v-model="form.password"
          type="password"
          placeholder="匿名可留空"
          show-password
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        type="warning"
        :loading="loading"
        @click="emit('discover', { ...form })"
      >
        开始发现
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  // 打开时带入的默认值（上次扫描网段、已保存的发现凭据）
  defaults: { type: Object, default: () => ({ subnet: '192.168.1', username: '', password: '' }) },
})
const emit = defineEmits(['update:modelValue', 'discover'])

const form = reactive({ subnet: '192.168.1', username: '', password: '' })
watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      form.subnet = props.defaults.subnet || '192.168.1'
      form.username = props.defaults.username || ''
      form.password = props.defaults.password || ''
    }
  }
)
</script>
