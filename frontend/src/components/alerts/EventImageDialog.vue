<template>
  <el-dialog
    :model-value="modelValue"
    title="告警现场图"
    width="720px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="event-image-box">
      <el-image
        v-if="url"
        :src="url"
        fit="contain"
        :preview-src-list="[url]"
        preview-teleported
        style="width: 100%; max-height: 480px"
      />
      <el-empty v-else-if="!loading" description="该事件关联的检测记录无现场图（可能未开启留存或已被清理）" />
    </div>
  </el-dialog>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  url: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
</script>

<style scoped>
.event-image-box { min-height: 200px; display: flex; align-items: center; justify-content: center; }
</style>
