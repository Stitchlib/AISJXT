<template>
  <div>
    <div class="head">
      <h2>系统配置</h2>
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
    </div>

    <el-card v-loading="loading" shadow="hover" style="margin-bottom: 16px">
      <el-form :model="form" label-width="160px">
        <el-divider content-position="left">检测参数</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="置信度阈值">
              <el-input-number v-model="form.confidence_threshold" :min="0" :max="1" :step="0.01" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="IOU 阈值">
              <el-input-number v-model="form.iou_threshold" :min="0" :max="1" :step="0.01" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="启用仿真数据">
              <el-switch v-model="form.enable_simulation" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="推送间隔(帧)">
              <el-input-number v-model="form.push_interval_frames" :min="1" :step="1" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="模型路径">
          <el-input v-model="form.model_path" placeholder="如 models/best.pt" />
        </el-form-item>

        <el-divider content-position="left">SMTP 邮件推送</el-divider>
        <el-form-item label="启用 SMTP">
          <el-switch v-model="form.smtp_enabled" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="SMTP 主机">
              <el-input v-model="form.smtp_host" :disabled="!form.smtp_enabled" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="SMTP 端口">
              <el-input-number v-model="form.smtp_port" :disabled="!form.smtp_enabled" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="加密方式">
              <el-select v-model="form.smtp_mode" :disabled="!form.smtp_enabled" style="width: 100%">
                <el-option label="SSL（端口 465）" value="ssl" />
                <el-option label="STARTTLS（端口 587）" value="starttls" />
                <el-option label="明文（内网/调试）" value="plain" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="SMTP 账号">
              <el-input v-model="form.smtp_user" :disabled="!form.smtp_enabled" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="SMTP 密码">
              <el-input v-model="form.smtp_pass" :disabled="!form.smtp_enabled" type="password" show-password placeholder="授权码/密码" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="发件人">
          <el-input v-model="form.smtp_from" :disabled="!form.smtp_enabled" placeholder="no-reply@example.com" />
        </el-form-item>

        <el-divider content-position="left">瑕疵类型</el-divider>
        <div v-if="form.defect_types.length === 0" class="empty-tip">暂无瑕疵类型，请添加。</div>
        <el-table :data="form.defect_types" border size="small" style="margin-bottom: 12px">
          <el-table-column label="名称" min-width="120">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="颜色" width="120">
            <template #default="{ row }">
              <el-color-picker v-model="row.color" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="启用" width="90" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center">
            <template #default="{ $index }">
              <el-button type="danger" text size="small" @click="removeDefect($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button @click="addDefect">+ 添加瑕疵类型</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { configApi } from '@/api'

const loading = ref(false)
const saving = ref(false)
const form = reactive({
  confidence_threshold: 0.5,
  iou_threshold: 0.5,
  enable_simulation: false,
  model_path: '',
  push_interval_frames: 10,
  smtp_enabled: false,
  smtp_host: '',
  smtp_port: 465,
  smtp_mode: 'ssl',
  smtp_user: '',
  smtp_pass: '',
  smtp_from: '',
  defect_types: [],
})

function assign(def) {
  form.confidence_threshold = def.confidence_threshold ?? 0.5
  form.iou_threshold = def.iou_threshold ?? 0.5
  form.enable_simulation = !!def.enable_simulation
  form.model_path = def.model_path || ''
  form.push_interval_frames = def.push_interval_frames ?? 10
  form.smtp_enabled = !!def.smtp_enabled
  form.smtp_host = def.smtp_host || ''
  form.smtp_port = def.smtp_port ?? 465
  form.smtp_mode = def.smtp_mode || 'ssl'
  form.smtp_user = def.smtp_user || ''
  form.smtp_pass = def.smtp_pass || ''
  form.smtp_from = def.smtp_from || ''
  form.defect_types = Array.isArray(def.defect_types) ? def.defect_types.map((d) => ({ ...d })) : []
}

function addDefect() {
  form.defect_types.push({ name: '', color: '#409eff', enabled: true })
}
function removeDefect(i) {
  form.defect_types.splice(i, 1)
}

async function load() {
  loading.value = true
  try {
    const def = await configApi.get()
    assign(def)
  } catch (e) {
    ElMessage.error('加载配置失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {
      confidence_threshold: form.confidence_threshold,
      iou_threshold: form.iou_threshold,
      enable_simulation: form.enable_simulation,
      model_path: form.model_path,
      push_interval_frames: form.push_interval_frames,
      smtp_enabled: form.smtp_enabled,
      smtp_host: form.smtp_host,
      smtp_port: form.smtp_port,
      smtp_mode: form.smtp_mode,
      smtp_user: form.smtp_user,
      smtp_pass: form.smtp_pass,
      smtp_from: form.smtp_from,
      defect_types: form.defect_types.map((d) => ({
        name: d.name,
        color: d.color,
        enabled: !!d.enabled,
      })),
    }
    const updated = await configApi.update(payload)
    assign(updated)
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.empty-tip { color: #909399; font-size: 13px; margin: 8px 0; }
</style>
