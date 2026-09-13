<template>
  <el-dialog
    :model-value="modelValue"
    :title="rule ? '编辑规则' : '新建规则'"
    width="460px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form
      :model="form"
      label-width="100px"
    >
      <el-form-item label="名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="指标">
        <el-select
          v-model="form.metric"
          style="width: 100%"
        >
          <el-option
            label="缺陷率"
            value="defect_rate"
          />
          <el-option
            label="缺陷数"
            value="defect_count"
          />
          <el-option
            label="处理耗时(ms)"
            value="processing_time_ms"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="运算符">
        <el-select
          v-model="form.operator"
          style="width: 100%"
        >
          <el-option
            label="大于 (>)"
            value="gt"
          />
          <el-option
            label="大于等于 (≥)"
            value="ge"
          />
          <el-option
            label="小于 (<)"
            value="lt"
          />
          <el-option
            label="小于等于 (≤)"
            value="le"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="阈值">
        <el-input-number
          v-model="form.threshold"
          :step="0.1"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="冷却(秒)">
        <el-input-number
          v-model="form.cooldown_seconds"
          :min="0"
          :max="604800"
          :step="30"
          style="width: 100%"
        />
        <div class="cooldown-tip">
          冷却窗口内重复命中不重复通知，仅累计次数；0=不冷却
        </div>
      </el-form-item>
      <el-form-item label="作用域">
        <el-select
          v-model="form.scope"
          style="width: 100%"
        >
          <el-option
            label="全部摄像头"
            value="all"
          />
          <el-option
            v-for="c in cameras"
            :key="c.id"
            :label="c.name || c.id"
            :value="c.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="通知邮箱">
        <el-input
          v-model="form.notify_email"
          placeholder="可选"
        />
      </el-form-item>
      <!-- G3 多渠道通知：Webhook 渠道 -->
      <el-form-item label="Webhook 类型">
        <el-select
          v-model="form.webhook_type"
          style="width: 100%"
        >
          <el-option
            label="关闭"
            value=""
          />
          <el-option
            label="通用 (generic)"
            value="generic"
          />
          <el-option
            label="钉钉"
            value="dingtalk"
          />
          <el-option
            label="飞书"
            value="feishu"
          />
          <el-option
            label="企业微信"
            value="wecom"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="Webhook URL">
        <el-input
          v-model="form.webhook_url"
          placeholder="可选；留空则不推送 Webhook"
        />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button
        v-if="rule"
        :loading="webhookTesting"
        @click="emit('test-webhook')"
      >
        测试发送
      </el-button>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="saving"
        @click="onSave"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  webhookTesting: { type: Boolean, default: false },
  // 编辑时传入当前规则；新建时为 null
  rule: { type: Object, default: null },
  cameras: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'save', 'test-webhook', 'invalid'])

const form = reactive({
  name: '',
  metric: 'defect_rate',
  operator: 'gt',
  threshold: 0.1,
  scope: 'all',
  notify_email: '',
  webhook_type: '',
  webhook_url: '',
  cooldown_seconds: 0,
  enabled: true,
})

const DEFAULTS = {
  name: '', metric: 'defect_rate', operator: 'gt', threshold: 0.1, scope: 'all',
  notify_email: '', webhook_type: '', webhook_url: '', cooldown_seconds: 0, enabled: true,
}

// 每次打开按当前规则回填（或恢复新建默认值）
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    const r = props.rule
    form.name = r ? r.name : DEFAULTS.name
    form.metric = r ? r.metric : DEFAULTS.metric
    form.operator = r ? r.operator : DEFAULTS.operator
    form.threshold = r ? r.threshold : DEFAULTS.threshold
    form.scope = r ? r.scope || 'all' : DEFAULTS.scope
    form.cooldown_seconds = r ? r.cooldown_seconds ?? 0 : 0
    form.notify_email = r ? r.notify_email || '' : ''
    form.webhook_type = r ? r.webhook_type || '' : ''
    form.webhook_url = r ? r.webhook_url || '' : ''
    form.enabled = r ? !!r.enabled : true
  }
)

function onSave() {
  if (!form.name) {
    emit('invalid', '请填写规则名称')
    return
  }
  emit('save', {
    name: form.name,
    metric: form.metric,
    operator: form.operator,
    threshold: form.threshold,
    scope: form.scope,
    cooldown_seconds: form.cooldown_seconds ?? 0,
    notify_email: form.notify_email || undefined,
    webhook_type: form.webhook_type || undefined,
    webhook_url: form.webhook_url || undefined,
    enabled: form.enabled,
  })
}
</script>

<style scoped>
.cooldown-tip { font-size: 12px; color: #909399; line-height: 1.4; }
</style>
