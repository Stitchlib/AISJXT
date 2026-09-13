<template>
  <el-dialog
    :model-value="modelValue"
    title="告警人工判定"
    width="440px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form label-width="80px">
      <el-form-item label="事件">
        <span class="verdict-event">#{{ target?.id }} {{ target?.message }}</span>
      </el-form-item>
      <el-form-item label="判定">
        <el-radio-group v-model="form.verdict">
          <el-radio label="confirmed">
            确认缺陷
          </el-radio>
          <el-radio label="false_positive">
            误报
          </el-radio>
          <el-radio label="missed">
            漏报
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="备注">
        <el-input
          v-model="form.remark"
          type="textarea"
          :rows="2"
          placeholder="可选，如：背景纹理干扰"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="saving"
        @click="emit('save', target.id, { verdict: form.verdict, remark: form.remark || undefined })"
      >
        提交判定
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  target: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'save'])

const form = reactive({ verdict: 'confirmed', remark: '' })

watch(
  () => props.target,
  (row) => {
    if (!row) return
    form.verdict = row.verdict && row.verdict !== 'pending' ? row.verdict : 'confirmed'
    form.remark = row.remark || ''
  }
)
</script>

<style scoped>
.verdict-event { color: #606266; font-size: 13px; }
</style>
