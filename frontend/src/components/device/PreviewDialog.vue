<template>
  <el-dialog
    :model-value="modelValue"
    title="实时画面预览"
    width="700px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="preview-wrap">
      <img v-if="src" :key="reloadKey" :src="src" class="preview" alt="实时画面预览" @error="onError" />
      <el-empty v-else description="无可预览设备" />
      <el-alert v-if="errorMsg" type="error" :closable="false" :title="errorMsg" style="margin-top: 8px" />
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" @click="reload">刷新预览</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { cameraApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  cameraId: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const src = ref('')
const errorMsg = ref('')
const reloadKey = ref(0)

// 通过一次性 stream ticket 取流（M7），避免 JWT 进 URL
async function load() {
  if (!props.cameraId) {
    src.value = ''
    return
  }
  errorMsg.value = ''
  try {
    src.value = await cameraApi.videoUrl(props.cameraId, 12)
  } catch (e) {
    src.value = ''
    errorMsg.value = '预览地址获取失败：' + (e.response?.data?.detail || e.message)
  }
}

function onError() {
  errorMsg.value = '预览加载失败：摄像头可能已停用、网络不可达或令牌失效'
}
function reload() {
  errorMsg.value = ''
  reloadKey.value += 1
  load()
}

watch(
  () => [props.modelValue, props.cameraId],
  ([open]) => {
    if (open) {
      reloadKey.value += 1
      load()
    }
  }
)
</script>

<style scoped>
.preview-wrap { width: 100%; min-height: 300px; background: #000; border-radius: 6px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.preview { width: 100%; display: block; }
</style>
